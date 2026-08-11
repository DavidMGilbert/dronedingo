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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from . import config as cfg
from .db import DB
from .hub import Hub
from .manager import Manager

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dronedingo")

BASE = Path(__file__).resolve().parents[2]
FRONTEND = BASE / "frontend"

db = DB()
hub = Hub()
manager = Manager(db, hub)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
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


@app.post("/api/alerts/test")
async def api_alerts_test():
    return await asyncio.to_thread(manager.alerter.test)


# ----------------------------- WebSocket -----------------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive / ignore client messages
    except WebSocketDisconnect:
        hub.disconnect(ws)
    except Exception:
        hub.disconnect(ws)


# ----------------------------- Static UI -----------------------------------
@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")


if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="static")
