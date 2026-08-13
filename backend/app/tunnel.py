"""Remote-access tunnel client — proprietary, outbound-only.

When remote access is enabled, this long-polls the relay for browser requests
addressed to this appliance, runs each against the appliance's own local UI, and
posts the response back. The appliance never accepts an inbound connection, so it
works behind DHCP / CGNAT with no port forwarding — the same store-and-forward
model as DroneDingo Push, authenticated with the appliance's per-node key.

The transport lives on shared PHP hosting (no persistent socket needed). If the
fleet outgrows that, only the relay side moves to a VPS — this client is unchanged.
"""
from __future__ import annotations
import asyncio
import base64
import json
import logging
import secrets
import urllib.error
import urllib.request

from . import net          # noqa: F401 — pins the certifi CA bundle for HTTPS
from . import config as cfg
from . import push

log = logging.getLogger("dronedingo")

LOCAL_BASE = "http://127.0.0.1:8000"          # this appliance's own web UI
_HOP = {"transfer-encoding", "connection", "content-length", "keep-alive"}

# Per-boot, in-memory secret proving a local request came from THIS appliance's
# own tunnel client. The auth guard trusts it to skip a second login for remote
# users (who already authenticated at the dashboard). It never leaves the box,
# is random each boot, and the client strips any browser-supplied copy — so it
# cannot be forged from the LAN or through the tunnel.
AUTH_TOKEN = secrets.token_hex(24)
AUTH_HEADER = "X-DD-Tunnel-Auth"

# Don't follow redirects locally — the browser must see the 3xx (e.g. login).
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):      # noqa: D401
        return None


_opener = urllib.request.build_opener(_NoRedirect)

_task: "asyncio.Task | None" = None
_stop: "asyncio.Event | None" = None


def enabled() -> bool:
    st = cfg.get_state()
    if "remote_access_enabled" in st:
        return bool(st["remote_access_enabled"])
    return bool((cfg.load().get("remote_access") or {}).get("enabled", False))


def _relay() -> str:
    return push.registration_base()


# --- sync workers (run in a thread) ----------------------------------------
def _poll_once(node: str, key: str) -> list[dict]:
    req = urllib.request.Request(
        _relay() + "/api/tunnel-poll.php",
        data=json.dumps({"node": node, "key": key}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=35) as r:
        return (json.loads(r.read()) or {}).get("requests", [])


def _run_local(msg: dict):
    method = msg.get("method", "GET")
    path = msg.get("path", "/")
    body = base64.b64decode(msg["body"]) if msg.get("body") else None
    req = urllib.request.Request(LOCAL_BASE + path, data=body, method=method)
    for k, v in (msg.get("headers") or {}).items():
        # No compression; and strip any browser-supplied auth header so it can't
        # forge the trusted marker we add below.
        if k.lower() in ("accept-encoding", "host", "content-length",
                         AUTH_HEADER.lower()):
            continue
        try:
            req.add_header(k, v)
        except Exception:
            pass
    # Mark the request as coming from our own tunnel — lets the appliance skip a
    # second login for a user the dashboard already authenticated.
    req.add_header(AUTH_HEADER, AUTH_TOKEN)
    try:
        with _opener.open(req, timeout=30) as r:
            return r.status, dict(r.headers.items()), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers.items()), e.read()
    except Exception as exc:
        return 502, {"Content-Type": "text/plain"}, str(exc).encode()


def _respond(node: str, key: str, rid: int, status: int, headers: dict, data: bytes):
    headers = {k: v for k, v in headers.items() if k.lower() not in _HOP}
    payload = {"node": node, "key": key, "id": rid, "status": status,
               "headers": headers,
               "body": base64.b64encode(data).decode() if data else ""}
    req = urllib.request.Request(
        _relay() + "/api/tunnel-respond.php",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        r.read()


# --- async loop ------------------------------------------------------------
async def _handle(node: str, key: str, msg: dict):
    status, headers, data = await asyncio.to_thread(_run_local, msg)
    await asyncio.to_thread(_respond, node, key, msg.get("id"), status, headers, data)


async def _loop(stop: "asyncio.Event"):
    log.info("remote access tunnel started")
    node = cfg.get_node_id()
    while not stop.is_set():
        key = push.ensure_relay_key()
        try:
            reqs = await asyncio.to_thread(_poll_once, node, key)
        except Exception as exc:
            log.debug("tunnel poll failed: %s", exc)
            await asyncio.sleep(5)
            continue
        if reqs:
            await asyncio.gather(*(_handle(node, key, m) for m in reqs),
                                 return_exceptions=True)
    log.info("remote access tunnel stopped")


def start() -> bool:
    """Start the tunnel loop if enabled and not already running."""
    global _task, _stop
    if not enabled():
        return False
    if _task and not _task.done():
        return True
    _stop = asyncio.Event()
    _task = asyncio.get_event_loop().create_task(_loop(_stop))
    return True


def stop() -> None:
    global _task, _stop
    if _stop:
        _stop.set()
    _task = None


def is_running() -> bool:
    return bool(_task and not _task.done())


# --- first-boot wizard: dashboard account + station claim (via the relay) ---
def _relay_json(path: str, payload: dict | None = None, method: str = "POST",
                timeout: int = 15) -> dict:
    url = _relay() + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"ok": False, "error": f"server error ({e.code})"}
    except Exception as exc:
        return {"ok": False, "error": f"could not reach the dashboard service: {exc}"}


def account_signup(email: str, password: str) -> dict:
    return _relay_json("/api/account-signup.php", {"email": email, "password": password})


def account_login(email: str, password: str) -> dict:
    return _relay_json("/api/account-login.php", {"email": email, "password": password})


def account_import(email: str, password: str) -> dict:
    return _relay_json("/api/account-import.php", {"email": email, "password": password})


def subdomain_check(sub: str) -> dict:
    from urllib.parse import quote
    return _relay_json("/api/subdomain-check.php?s=" + quote(sub), method="GET", timeout=10)


def station_claim(token: str, subdomain: str, label: str) -> dict:
    return _relay_json("/api/station-claim.php", {
        "node": cfg.get_node_id(), "key": push.ensure_relay_key(),
        "token": token, "subdomain": subdomain, "label": label})
