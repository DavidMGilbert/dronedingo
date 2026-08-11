"""Software update checking and installation.

Two channels (see docs/UPDATE_PROTOCOL.md):

* **website** — when ``updates.check_url`` is set (production). The appliance
  fetches a signed manifest from dronedingo.com.au, downloads the release zip,
  verifies its SHA-256 and (if a public key is configured) its Ed25519
  signature, then hands the *verified* zip to the privileged apply step.
* **git** — when the install directory is a git checkout and no check_url is
  set (developer flow).

The web process is unprivileged; the actual file swap + service restart runs
through ``deploy/update.sh`` under a narrow sudoers rule. Downloads and all
verification happen *before* the privileged step, and the expected hash is
re-checked inside the root helper, so root only ever acts on a verified file.
"""
from __future__ import annotations
import base64
import hashlib
import json
import logging
import re
import subprocess
import urllib.request
from pathlib import Path

from . import __version__
from . import config as cfg

log = logging.getLogger("dronedingo")

APP_ROOT = Path(__file__).resolve().parents[2]
_UPDATE_SCRIPT = APP_ROOT / "deploy" / "update.sh"
_STAGING = APP_ROOT / "data" / "updates"
_GIT_TIMEOUT = 30
_DL_TIMEOUT = 120


# --------------------------------------------------------------------------
# version helpers
# --------------------------------------------------------------------------
def _semver(v: str) -> tuple:
    """Parse 'X.Y.Z' (ignoring any pre-release suffix) into a comparable tuple."""
    core = re.split(r"[-+]", str(v).strip(), maxsplit=1)[0]
    parts = core.split(".")
    out = []
    for p in parts[:3]:
        out.append(int(p) if p.isdigit() else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def _newer(candidate: str, current: str) -> bool:
    return _semver(candidate) > _semver(current)


# --------------------------------------------------------------------------
# git (developer flow)
# --------------------------------------------------------------------------
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
    updates = cfg.load().get("updates") or {}
    if updates.get("check_url"):
        ver["channel"] = "website"
    elif _is_git_checkout():
        rc, sha = _git("rev-parse", "--short", "HEAD")
        if rc == 0:
            ver["build"] = sha
        ver["channel"] = "git"
    return ver


# --------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------
def check() -> dict:
    updates = cfg.load().get("updates") or {}
    if updates.get("check_url"):
        return _check_website(updates)
    if _is_git_checkout():
        return _check_git(updates.get("branch", "main"))
    return {"channel": "none", "available": False, **current_version(),
            "message": "This build has no update channel configured."}


def _check_git(branch: str) -> dict:
    base = current_version()
    rc, out = _git("fetch", "--quiet", "origin", branch)
    if rc != 0:
        return {**base, "available": False, "error": True,
                "message": f"Could not reach the update server. {out}".strip()}
    _, local = _git("rev-parse", "HEAD")
    _, remote = _git("rev-parse", f"origin/{branch}")
    _, behind = _git("rev-list", "--count", f"HEAD..origin/{branch}")
    _, notes = _git("log", "--oneline", "--no-decorate", f"HEAD..origin/{branch}")
    available = local != remote and behind.isdigit() and int(behind) > 0
    return {**base, "available": available,
            "behind": int(behind) if behind.isdigit() else 0,
            "latest_build": remote[:7] if remote else None, "notes": notes,
            "message": (f"Update available — {behind} new change(s)." if available
                        else "You are on the latest version.")}


def _manifest_request(updates: dict) -> urllib.request.Request:
    node = cfg.get_node_id()
    url = (f"{updates['check_url']}?channel={updates.get('channel', 'stable')}"
           f"&current={__version__}&node={node}")
    req = urllib.request.Request(url, headers={
        "User-Agent": f"DroneDingo/{__version__} ({node})",
        "Accept": "application/json",
    })
    if updates.get("token"):
        req.add_header("Authorization", f"Bearer {updates['token']}")
    return req


def _check_website(updates: dict) -> dict:
    base = current_version()
    try:
        with urllib.request.urlopen(_manifest_request(updates), timeout=20) as r:
            if r.status == 204:
                return {**base, "available": False, "message": "No releases yet."}
            manifest = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (204, 404):
            return {**base, "available": False, "message": "No releases yet."}
        msg = ("Update server rejected the request (check the appliance token)."
               if exc.code == 401 else f"Update server error ({exc.code}).")
        return {**base, "available": False, "error": True, "message": msg}
    except Exception as exc:
        return {**base, "available": False, "error": True,
                "message": f"Could not reach the update server: {exc}"}

    latest = str(manifest.get("version", "")).strip()
    available = bool(latest) and _newer(latest, __version__)
    return {**base, "available": available, "latest_version": latest,
            "notes": manifest.get("notes", ""),
            "released": manifest.get("released"),
            "message": (f"Version {latest} is available."
                        if available else "You are on the latest version.")}


# --------------------------------------------------------------------------
# install
# --------------------------------------------------------------------------
def install() -> dict:
    updates = cfg.load().get("updates") or {}
    if updates.get("check_url"):
        return _install_website(updates)
    return _install_git()


def _install_git() -> dict:
    if not _UPDATE_SCRIPT.exists():
        return {"ok": False, "message": "Update script not found on this node."}
    branch = (cfg.load().get("updates") or {}).get("branch", "main")
    return _run_apply(["git", branch])


def _verify_signature(digest: bytes, signature_b64: str, public_key_b64: str) -> bool:
    """Verify an Ed25519 signature over the release's SHA-256 digest."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        raise RuntimeError("release is signed but 'cryptography' is not installed")
    from cryptography.exceptions import InvalidSignature
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        pub.verify(base64.b64decode(signature_b64), digest)
        return True
    except (InvalidSignature, ValueError):
        return False


def _install_website(updates: dict) -> dict:
    # 1. fetch manifest
    try:
        with urllib.request.urlopen(_manifest_request(updates), timeout=20) as r:
            manifest = json.loads(r.read())
    except Exception as exc:
        return {"ok": False, "message": f"Could not fetch manifest: {exc}"}

    version = str(manifest.get("version", "")).strip()
    art = manifest.get("artifact") or {}
    if not version or not art.get("url") or not art.get("sha256"):
        return {"ok": False, "message": "Manifest is incomplete."}
    if not _newer(version, __version__):
        return {"ok": False, "message": "Already on the latest version."}

    # 2. download
    _STAGING.mkdir(parents=True, exist_ok=True)
    zip_path = _STAGING / f"dronedingo-{version}.zip"
    try:
        dl = urllib.request.Request(art["url"])
        if updates.get("token"):
            dl.add_header("Authorization", f"Bearer {updates['token']}")
        with urllib.request.urlopen(dl, timeout=_DL_TIMEOUT) as r, \
                open(zip_path, "wb") as f:
            f.write(r.read())
    except Exception as exc:
        return {"ok": False, "message": f"Download failed: {exc}"}

    # 3. verify size + sha256
    data = zip_path.read_bytes()
    if art.get("size") and len(data) != int(art["size"]):
        zip_path.unlink(missing_ok=True)
        return {"ok": False, "message": "Downloaded size does not match manifest."}
    digest = hashlib.sha256(data).digest()
    if digest.hex() != art["sha256"].lower():
        zip_path.unlink(missing_ok=True)
        return {"ok": False, "message": "Checksum mismatch — download rejected."}

    # 4. verify signature (required when a public key is configured)
    pub = updates.get("public_key")
    if pub:
        sig = art.get("signature")
        if not sig:
            zip_path.unlink(missing_ok=True)
            return {"ok": False, "message": "Release is unsigned but this "
                    "appliance requires a signature — rejected."}
        try:
            if not _verify_signature(digest, sig, pub):
                zip_path.unlink(missing_ok=True)
                return {"ok": False, "message": "Signature invalid — rejected."}
        except RuntimeError as exc:
            return {"ok": False, "message": str(exc)}
    else:
        log.warning("installing UNSIGNED release %s (no updates.public_key set)",
                    version)

    # 5. privileged apply (root re-checks the hash before extracting)
    return _run_apply(["from-zip", str(zip_path), version, art["sha256"]])


def _run_apply(args: list[str]) -> dict:
    try:
        p = subprocess.run(["sudo", "-n", "bash", str(_UPDATE_SCRIPT), *args],
                           capture_output=True, text=True, timeout=900)
        ok = p.returncode == 0
        return {"ok": ok, "output": (p.stdout + p.stderr)[-4000:],
                "message": "Update installed; the service is restarting."
                           if ok else "Update failed — see log."}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Update timed out."}
    except Exception as exc:
        return {"ok": False, "message": f"Update error: {exc}"}
