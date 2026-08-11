"""Software update checking and installation.

Two update channels are supported so the same code serves both the current
git-clone appliance and a future managed/SaaS fleet:

* **git** — when the install directory is a git checkout, compare the local
  HEAD against the tracked remote branch.
* **manifest** — when ``updates.manifest_url`` is set, fetch a small JSON
  document ``{"version": "...", "notes": "...", "url": "..."}`` and compare it
  against the running version.

Installation runs ``deploy/update.sh`` (which pulls, reinstalls deps and
restarts the service). That script is the only thing granted elevated rights,
via a narrow sudoers entry created by the installer — the web process itself
stays unprivileged. All update endpoints are behind authentication.
"""
from __future__ import annotations
import json
import logging
import subprocess
import urllib.request
from pathlib import Path

from . import __version__
from . import config as cfg

log = logging.getLogger("dronedingo")

APP_ROOT = Path(__file__).resolve().parents[2]
_UPDATE_SCRIPT = APP_ROOT / "deploy" / "update.sh"
_GIT_TIMEOUT = 30


def _git(*args: str) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", "-C", str(APP_ROOT), *args],
                           capture_output=True, text=True, timeout=_GIT_TIMEOUT)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as exc:
        return 1, str(exc)


def _is_git_checkout() -> bool:
    return (APP_ROOT / ".git").exists() and _git("rev-parse", "--git-dir")[0] == 0


def current_version() -> dict:
    ver = {"version": __version__, "build": None, "channel": "none"}
    if _is_git_checkout():
        rc, sha = _git("rev-parse", "--short", "HEAD")
        if rc == 0:
            ver["build"] = sha
        ver["channel"] = "git"
    elif (cfg.load().get("updates") or {}).get("manifest_url"):
        ver["channel"] = "manifest"
    return ver


def check() -> dict:
    """Return update availability without modifying anything."""
    updates = cfg.load().get("updates") or {}
    manifest_url = updates.get("manifest_url")

    if manifest_url:
        return _check_manifest(manifest_url)
    if _is_git_checkout():
        return _check_git(updates.get("branch", "main"))
    return {"channel": "none", "available": False,
            "message": "This build has no update channel configured.",
            **current_version()}


def _check_git(branch: str) -> dict:
    base = current_version()
    rc, out = _git("fetch", "--quiet", "origin", branch)
    if rc != 0:
        # Most commonly: private repo with no deploy key on the appliance.
        return {**base, "available": False, "error": True,
                "message": f"Could not reach the update server. {out}".strip()}
    _, local = _git("rev-parse", "HEAD")
    _, remote = _git("rev-parse", f"origin/{branch}")
    _, behind = _git("rev-list", "--count", f"HEAD..origin/{branch}")
    _, log_out = _git("log", "--oneline", "--no-decorate",
                      f"HEAD..origin/{branch}")
    available = local != remote and (behind.isdigit() and int(behind) > 0)
    return {
        **base, "available": available,
        "behind": int(behind) if behind.isdigit() else 0,
        "latest_build": remote[:7] if remote else None,
        "notes": log_out,
        "message": (f"Update available — {behind} new change(s)." if available
                    else "You are on the latest version."),
    }


def _check_manifest(url: str) -> dict:
    base = current_version()
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            manifest = json.loads(resp.read())
    except Exception as exc:
        return {**base, "available": False, "error": True,
                "message": f"Could not reach the update server: {exc}"}
    latest = str(manifest.get("version", "")).strip()
    available = bool(latest) and latest != base["version"]
    return {
        **base, "available": available, "latest_version": latest,
        "notes": manifest.get("notes", ""),
        "download_url": manifest.get("url"),
        "message": (f"Version {latest} is available."
                    if available else "You are on the latest version."),
    }


def install() -> dict:
    """Invoke the privileged update script. Returns immediately-captured output.

    The service typically restarts as part of the script, so the HTTP response
    may be cut short — the UI treats a dropped connection after a 2xx as
    'installing, reconnecting'.
    """
    if not _UPDATE_SCRIPT.exists():
        return {"ok": False, "message": "Update script not found on this node."}
    try:
        # sudo -n: never prompt; the installer grants exactly this command.
        p = subprocess.run(["sudo", "-n", "bash", str(_UPDATE_SCRIPT)],
                           capture_output=True, text=True, timeout=600)
        ok = p.returncode == 0
        return {"ok": ok, "output": (p.stdout + p.stderr)[-4000:],
                "message": "Update installed; the service is restarting."
                           if ok else "Update failed — see log."}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Update timed out."}
    except Exception as exc:
        return {"ok": False, "message": f"Update error: {exc}"}
