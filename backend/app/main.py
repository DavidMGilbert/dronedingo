"""DroneDingo — FastAPI application entrypoint.

Serves the branded web UI, a REST API for config/history/playback, and a
WebSocket stream of live detections.
"""
from __future__ import annotations
import asyncio
import contextlib
import logging
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse, FileResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from . import config as cfg
from . import auth, system, updater, push
from .db import DB
from .hub import Hub
from .manager import Manager
from .mapstyle import build_style
from .tiles import TileStore
from . import __version__

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dronedingo")

BASE = Path(__file__).resolve().parents[2]
FRONTEND = BASE / "frontend"

db = DB()
hub = Hub()
manager = Manager(db, hub)
tile_store: TileStore | None = None


def _open_basemap() -> None:
    """Open the offline basemap if one is configured and present."""
    global tile_store
    basemap = (cfg.load().get("map", {}).get("basemap") or {})
    path = basemap.get("path")
    if not path:
        return
    p = Path(path)
    if not p.is_absolute():
        p = BASE / p
    try:
        tile_store = TileStore(p)
    except Exception as exc:
        # A missing basemap must not stop the appliance — fall back online.
        log.warning("offline basemap unavailable (%s); using online tiles", exc)
        tile_store = None


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    _open_basemap()
    push.ensure_keys()          # generate the VAPID key pair on first run
    push.start_poller()         # collect device registrations from the relay
    await manager.start()
    prune_task = asyncio.create_task(_prune_loop())
    log.info("DroneDingo online — UI at http://%s:%s",
             cfg.load()["server"]["host"], cfg.load()["server"]["port"])
    yield
    prune_task.cancel()
    await manager.stop()


async def _prune_loop():
    while True:
        with contextlib.suppress(Exception):
            removed = await db.prune(cfg.load().get("retention_days", 90))
            if removed:
                log.info("pruned %d expired detections", removed)
        await asyncio.sleep(3600)


app = FastAPI(title="DroneDingo", lifespan=lifespan)

_AUTH_ENABLED = bool((cfg.load().get("auth") or {}).get("enabled", True))
_SESSION_HOURS = int((cfg.load().get("auth") or {}).get("session_hours", 168))

# Paths reachable without a session: the login flow, unbranded static assets,
# and the device push-registration PWA (which authenticates with a reg token).
_PUBLIC_PREFIXES = ("/login", "/api/auth", "/css/", "/js/", "/vendor/", "/favicon",
                    "/push", "/api/push/pubkey", "/api/push/subscribe",
                    "/api/push/unsubscribe")


def _is_public(path: str) -> bool:
    return path == "/login" or any(path.startswith(p) for p in _PUBLIC_PREFIXES)


async def _auth_guard(request: Request, call_next):
    path = request.url.path
    # Gate first: unauthenticated APIs get 401, pages redirect to login.
    if _AUTH_ENABLED and not _is_public(path) and not request.session.get("uid"):
        if path.startswith(("/api/", "/tiles/")):
            return JSONResponse({"error": "authentication required"}, status_code=401)
        return RedirectResponse("/login")
    response = await call_next(request)
    # App HTML/JS/CSS must always revalidate, so a self-update reaches browsers
    # immediately (StaticFiles' ETag then serves 304 when unchanged). Vendored
    # libraries/fonts keep their default long-lived caching.
    if path in ("/", "/login") or path.startswith(("/js/", "/css/")):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


# Middleware order matters: the LAST added runs OUTERMOST. SessionMiddleware
# must wrap the guard so request.session is populated before the guard reads it.
app.add_middleware(BaseHTTPMiddleware, dispatch=_auth_guard)   # inner
app.add_middleware(                                            # outer
    SessionMiddleware, secret_key=auth.session_secret(),
    max_age=_SESSION_HOURS * 3600, same_site="lax", https_only=False,
)


# ----------------------------- Auth ----------------------------------------
@app.get("/api/auth/status")
async def api_auth_status(request: Request):
    return {"authenticated": bool(request.session.get("uid")),
            "configured": auth.is_configured(),
            "auth_enabled": _AUTH_ENABLED}


@app.post("/api/auth/login")
async def api_auth_login(request: Request, payload: dict):
    email = payload.get("email", "")
    password = payload.get("password", "")
    # First run: no admin yet — this call creates the admin credentials.
    if not auth.is_configured():
        try:
            auth.set_credentials(email, password)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        request.session["uid"] = auth.get_email()
        return {"ok": True, "created": True}
    if auth.verify(email, password):
        request.session["uid"] = auth.get_email()
        return {"ok": True}
    return JSONResponse({"ok": False, "error": "Incorrect email or password."},
                        status_code=401)


@app.post("/api/auth/logout")
async def api_auth_logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/auth/whoami")
async def api_auth_whoami(request: Request):
    return {"email": request.session.get("uid")}


@app.post("/api/auth/password")
async def api_auth_password(request: Request, payload: dict):
    try:
        auth.change_password(payload.get("current", ""), payload.get("new", ""))
    except (PermissionError, ValueError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return {"ok": True}


@app.post("/api/auth/email")
async def api_auth_email(request: Request, payload: dict):
    try:
        auth.change_email(payload.get("email", ""), payload.get("password", ""))
    except (PermissionError, ValueError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    request.session["uid"] = auth.get_email()
    return {"ok": True}


# ----------------------------- REST API ------------------------------------
@app.get("/api/config")
async def api_config():
    c = cfg.load()
    return {
        "brand": c["brand"],
        "map": c["map"],
        "site": c["site"],
        "node_id": c["site"]["node_id"],
    }


@app.post("/api/home")
async def api_set_home(payload: dict):
    lat = float(payload["lat"])
    lon = float(payload["lon"])
    label = payload.get("label")
    home = cfg.set_home(lat, lon, label)
    return {"ok": True, "home": home}


@app.get("/api/active")
async def api_active(window: float = 60.0):
    return {"detections": await db.active(window)}


@app.get("/api/detections")
async def api_detections(start: float, end: float):
    return {"detections": await db.range(start, end)}


@app.get("/api/events")
async def api_events(days: int = 30):
    return {"events": await db.events(since_days=days)}


@app.get("/api/bounds")
async def api_bounds():
    b = await db.bounds()
    b["now"] = time.time()
    return b


@app.get("/api/map/style")
async def api_map_style(request: Request, theme: str = "dark"):
    """MapLibre style, generated from the brand palette + basemap source."""
    style = build_style(cfg.load(), tile_store, theme=theme)
    # Tile URLs must be absolute for MapLibre; fill in this request's origin.
    origin = str(request.base_url).rstrip("/")
    for src in style.get("sources", {}).values():
        if "tiles" in src:
            src["tiles"] = [t.replace("{origin}", origin) for t in src["tiles"]]
    return JSONResponse(style)


@app.get("/api/map/info")
async def api_map_info():
    if tile_store is None:
        return {"offline": False, "source": "online raster tiles"}
    return {
        "offline": True, "file": tile_store.path.name,
        "format": tile_store.tile_format, "vector": tile_store.is_vector,
        "minzoom": tile_store.minzoom, "maxzoom": tile_store.maxzoom,
    }


@app.get("/tiles/{z}/{x}/{y}")
async def api_tile(z: int, x: int, y: int):
    if tile_store is None:
        return Response(status_code=404)
    data = await asyncio.to_thread(tile_store.get, z, x, y)
    if data is None:
        # An absent tile is normal (sparse extract) — 204 keeps MapLibre quiet.
        return Response(status_code=204)
    return Response(content=data, media_type=tile_store.content_type,
                    headers={"Cache-Control": "public, max-age=604800"})


@app.get("/api/alerts")
async def api_alerts_status():
    a = manager.alerter
    return {
        "enabled": a.enabled,
        "ntfy_topic": a.topic,
        "ntfy_server": a.server,
        "webhook": bool(a.webhook),
        "alert_ring_m": a.ring_m,
        "resight_after_s": a.resight_after_s,
    }


@app.get("/api/alerts/config")
async def api_alerts_config():
    """Full alerts config for the settings form."""
    a = (cfg.load().get("alerts") or {})
    return {
        "ntfy_topic": a.get("ntfy_topic"),
        "ntfy_server": a.get("ntfy_server") or "https://ntfy.sh",
        "webhook_url": a.get("webhook_url"),
        "alert_ring_m": manager.alerter.ring_m,
        "resight_after_s": a.get("resight_after_s", 300),
        "quiet_hours": a.get("quiet_hours"),
        "quiet_hours_suppress": bool(a.get("quiet_hours_suppress", False)),
    }


@app.post("/api/alerts/config")
async def api_alerts_config_save(payload: dict):
    """Persist alert settings from the UI and reload the alerter."""
    allowed = ("ntfy_topic", "ntfy_server", "webhook_url", "alert_ring_m",
               "resight_after_s", "quiet_hours", "quiet_hours_suppress")
    values = {}
    for k in allowed:
        if k not in payload:
            continue
        v = payload[k]
        if isinstance(v, str) and v.strip() == "":
            v = None                        # empty field clears the override
        if k in ("alert_ring_m", "resight_after_s") and v is not None:
            v = float(v)
        values[k] = v
    cfg.save_settings("alerts", values)
    manager.reload_alerter()
    return {"ok": True}


@app.post("/api/alerts/test")
async def api_alerts_test():
    return await asyncio.to_thread(manager.alerter.test)


# ----------------------------- DroneDingo Push -----------------------------
@app.get("/api/push/pubkey")
async def api_push_pubkey():
    return {"key": push.public_key_b64()}


@app.get("/api/push/status")
async def api_push_status():
    p = cfg.load().get("push") or {}
    return {"enabled": push.enabled(), "devices": push.subscription_count(),
            "public_url": p.get("public_url") or p.get("relay_url"),
            "node": cfg.get_node_id(), "pubkey": push.public_key_b64()}


@app.post("/api/push/reg-token")
async def api_push_reg_token():
    """Mint a short-lived token that lets a phone register via the QR."""
    return {"token": push.new_reg_token()}


@app.post("/api/push/subscribe")
async def api_push_subscribe(request: Request, payload: dict):
    if not (request.session.get("uid") or push.check_reg_token(payload.get("token", ""))):
        return JSONResponse({"ok": False, "error": "registration link expired — reopen the QR"}, status_code=401)
    try:
        push.add_subscription(payload)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return {"ok": True}


@app.post("/api/push/unsubscribe")
async def api_push_unsubscribe(payload: dict):
    push.remove_subscription(payload.get("endpoint", ""))
    return {"ok": True}


@app.post("/api/push/test")
async def api_push_test():
    return await asyncio.to_thread(
        push.notify, "DroneDingo test alert",
        "If you can read this, DroneDingo Push is working.", {"test": True})


@app.get("/push")
async def push_pwa():
    return FileResponse(FRONTEND / "push" / "index.html")


# ----------------------------- System / admin ------------------------------
@app.get("/api/system/status")
async def api_system_status():
    return await asyncio.to_thread(system.status)


@app.get("/api/system/network")
async def api_system_network():
    interfaces = await asyncio.to_thread(system.interfaces)
    current = await asyncio.to_thread(system.wifi_current)
    return {"interfaces": interfaces, "wifi": current}


@app.get("/api/system/wifi/scan")
async def api_wifi_scan():
    return {"networks": await asyncio.to_thread(system.wifi_scan)}


@app.post("/api/system/wifi/connect")
async def api_wifi_connect(payload: dict):
    return await asyncio.to_thread(
        system.wifi_connect, payload.get("ssid", ""),
        payload.get("password", ""), payload.get("iface"))


@app.post("/api/system/ethernet")
async def api_ethernet(payload: dict):
    return await asyncio.to_thread(
        system.configure_ethernet, payload.get("iface", ""),
        payload.get("mode", "dhcp"), payload.get("ip", ""),
        payload.get("gateway", ""), payload.get("dns", ""))


@app.post("/api/system/reboot")
async def api_system_reboot():
    return await asyncio.to_thread(system.reboot)


# ----------------------------- Updates -------------------------------------
@app.get("/api/update/check")
async def api_update_check():
    return await asyncio.to_thread(updater.check)


@app.post("/api/update/install")
async def api_update_install():
    return await asyncio.to_thread(updater.install)


@app.get("/api/update/os/check")
async def api_os_check():
    return await asyncio.to_thread(system.os_update_check)


@app.post("/api/update/os/install")
async def api_os_install():
    return await asyncio.to_thread(system.os_update_install)


@app.get("/api/about")
async def api_about():
    c = cfg.load()
    return {
        "brand": c["brand"],
        "node_id": c["site"]["node_id"],
        "version": updater.current_version(),
    }


# ----------------------------- WebSocket -----------------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    # The session cookie is available on the WS scope via SessionMiddleware.
    if _AUTH_ENABLED and not ws.session.get("uid"):
        await ws.close(code=1008)          # policy violation
        return
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive / ignore client messages
    except WebSocketDisconnect:
        hub.disconnect(ws)
    except Exception:
        hub.disconnect(ws)


# ----------------------------- Docs (legal / notices) ----------------------
def _doc_response(name: str) -> Response:
    path = BASE / "docs" / name if name != "NOTICES.md" else BASE / name
    if not path.exists():
        return Response("Not found", status_code=404)
    return FileResponse(path, media_type="text/markdown; charset=utf-8")


@app.get("/docs/legal")
async def doc_legal():
    return _doc_response("LEGAL.md")


@app.get("/docs/notices")
async def doc_notices():
    return _doc_response("NOTICES.md")


@app.get("/docs/alerts")
async def doc_alerts():
    return _doc_response("ALERTS.md")


# ----------------------------- Static UI -----------------------------------
@app.get("/login")
async def login_page():
    return FileResponse(FRONTEND / "login.html")


@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")


if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="static")
