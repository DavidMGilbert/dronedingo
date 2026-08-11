"""System status and network control for the admin UI.

Read-only status (CPU, memory, disk, temperature, service state, network
interfaces) is gathered straight from the OS. State-changing actions — joining
a WiFi network, applying OS updates, rebooting — are delegated to a single
privileged helper (``deploy/sysctl.sh``) that the installer authorises through
a narrow sudoers rule, so the web process itself never runs as root.

Everything is defensive: on a non-Linux dev box, or when a tool is missing,
functions return best-effort partial data rather than raising, so the admin API
still responds.
"""
from __future__ import annotations
import json
import logging
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

log = logging.getLogger("dronedingo")

APP_ROOT = Path(__file__).resolve().parents[2]
_HELPER = APP_ROOT / "deploy" / "sysctl.sh"


def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "command not found"
    except Exception as exc:
        return 1, str(exc)


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text().strip()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# read-only status
# ---------------------------------------------------------------------------
def _mem() -> dict:
    info = _read("/proc/meminfo")
    if not info:
        return {}
    vals = {}
    for line in info.splitlines():
        k, _, rest = line.partition(":")
        vals[k] = int(rest.strip().split()[0]) * 1024  # kB -> bytes
    total = vals.get("MemTotal")
    avail = vals.get("MemAvailable")
    if not total:
        return {}
    used = total - (avail or 0)
    return {"total": total, "used": used,
            "percent": round(used / total * 100, 1)}


def _cpu_temp() -> float | None:
    # Pi and most SBCs expose CPU temp here in millidegrees.
    for zone in Path("/sys/class/thermal").glob("thermal_zone*/temp") \
            if Path("/sys/class/thermal").exists() else []:
        raw = _read(str(zone))
        if raw and raw.isdigit():
            return round(int(raw) / 1000.0, 1)
    return None


def _uptime() -> float | None:
    up = _read("/proc/uptime")
    return float(up.split()[0]) if up else None


def _service_active(name: str = "dronedingo") -> str:
    rc, out = _run(["systemctl", "is-active", name], timeout=5)
    out = out.strip()
    if rc == 127 or "not found" in out.lower():
        return "n/a"          # no systemd (e.g. dev box)
    return out or ("active" if rc == 0 else "unknown")


def status() -> dict:
    disk = shutil.disk_usage("/") if os.path.exists("/") else \
        shutil.disk_usage(str(APP_ROOT))
    load = None
    try:
        load = [round(x, 2) for x in os.getloadavg()]
    except (OSError, AttributeError):
        pass
    return {
        "hostname": socket.gethostname(),
        "time": time.time(),
        "uptime_s": _uptime(),
        "load": load,
        "cpu_count": os.cpu_count(),
        "cpu_temp_c": _cpu_temp(),
        "memory": _mem(),
        "disk": {"total": disk.total, "used": disk.used,
                 "percent": round(disk.used / disk.total * 100, 1)},
        "service": _service_active(),
    }


# ---------------------------------------------------------------------------
# network
# ---------------------------------------------------------------------------
def interfaces() -> list[dict]:
    """List network interfaces with addresses (via `ip -j addr`)."""
    rc, out = _run(["ip", "-j", "addr"])
    if rc != 0:
        return []
    try:
        raw = json.loads(out)
    except Exception:
        return []
    result = []
    for itf in raw:
        name = itf.get("ifname", "")
        if name == "lo":
            continue
        addrs = [a.get("local") for a in itf.get("addr_info", [])
                 if a.get("family") == "inet"]
        result.append({
            "name": name,
            "type": "wifi" if name.startswith(("wlan", "wlp")) else
                    ("ethernet" if name.startswith(("eth", "enp", "en")) else "other"),
            "mac": itf.get("address"),
            "state": itf.get("operstate", "unknown"),
            "addresses": addrs,
        })
    return result


def wifi_scan(iface: str | None = None) -> list[dict]:
    """Scan for WiFi networks via nmcli."""
    cmd = ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "dev", "wifi", "list"]
    if iface:
        cmd += ["ifname", iface]
    rc, out = _run(cmd, timeout=25)
    if rc != 0:
        return []
    seen, nets = set(), []
    for line in out.splitlines():
        # nmcli -t escapes ':' inside fields as '\:'
        parts = line.replace("\\:", "\x00").split(":")
        parts = [p.replace("\x00", ":") for p in parts]
        if len(parts) < 4 or not parts[0]:
            continue
        ssid = parts[0]
        if ssid in seen:
            continue
        seen.add(ssid)
        nets.append({
            "ssid": ssid,
            "signal": int(parts[1]) if parts[1].isdigit() else 0,
            "security": parts[2] or "Open",
            "active": parts[3] == "*",
        })
    return sorted(nets, key=lambda n: n["signal"], reverse=True)


def wifi_current() -> dict | None:
    rc, out = _run(["nmcli", "-t", "-f", "NAME,DEVICE,TYPE", "connection", "show",
                    "--active"], timeout=10)
    if rc != 0:
        return None
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[2].endswith("wireless"):
            return {"name": parts[0], "device": parts[1]}
    return None


# ---------------------------------------------------------------------------
# privileged actions (delegated to the sudo helper)
# ---------------------------------------------------------------------------
def _helper(verb: str, *args: str, timeout: int = 120) -> dict:
    if not _HELPER.exists():
        return {"ok": False, "message": "System helper not installed on this node."}
    rc, out = _run(["sudo", "-n", "bash", str(_HELPER), verb, *args], timeout=timeout)
    return {"ok": rc == 0, "output": out[-3000:]}


def wifi_connect(ssid: str, password: str, iface: str | None = None) -> dict:
    if not ssid:
        return {"ok": False, "message": "SSID required."}
    args = [ssid, password or ""]
    if iface:
        args.append(iface)
    res = _helper("wifi-connect", *args, timeout=60)
    res.setdefault("message",
                   "Connected." if res.get("ok") else "Could not connect.")
    return res


def os_update_check() -> dict:
    res = _helper("os-check", timeout=180)
    count = 0
    if res.get("ok"):
        # helper prints one upgradable package per line
        count = sum(1 for ln in (res.get("output") or "").splitlines() if ln.strip())
    return {"ok": res.get("ok", False), "upgradable": count,
            "output": res.get("output", ""),
            "message": (f"{count} OS update(s) available." if count else
                        "The operating system is up to date.")
            if res.get("ok") else "Could not check OS updates."}


def os_update_install() -> dict:
    res = _helper("os-upgrade", timeout=1800)
    res.setdefault("message", "OS updates installed." if res.get("ok")
                   else "OS update failed.")
    return res


def reboot() -> dict:
    res = _helper("reboot", timeout=10)
    res.setdefault("message", "Rebooting…" if res.get("ok") else "Reboot failed.")
    return res
