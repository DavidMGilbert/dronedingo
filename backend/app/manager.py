"""Wires detection sources into the async app.

Sources run in daemon threads and call ``emit`` (thread-safe). Detections are
placed on an asyncio queue, then a single consumer persists them and fans them
out to WebSocket clients. This keeps all DB / broadcast work on the event loop.
"""
from __future__ import annotations
import asyncio
import logging
import time

from .models import Detection
from .db import DB
from .hub import Hub
from .geo import haversine_m, bearing_deg, compass
from . import config as cfg

log = logging.getLogger("skywarden")

_SOURCE_REGISTRY = {}


def _load_registry():
    if _SOURCE_REGISTRY:
        return _SOURCE_REGISTRY
    from .sources.simulator import Simulator
    from .sources.wifi_remoteid import WifiRemoteID
    from .sources.bt_remoteid import BtRemoteID
    from .sources.rtlsdr_scan import RtlSdrScan
    _SOURCE_REGISTRY.update({
        "simulator": Simulator,
        "wifi_remoteid": WifiRemoteID,
        "bt_remoteid": BtRemoteID,
        "rtlsdr_scan": RtlSdrScan,
    })
    return _SOURCE_REGISTRY


class Manager:
    def __init__(self, db: DB, hub: Hub) -> None:
        self.db = db
        self.hub = hub
        self.loop: asyncio.AbstractEventLoop | None = None
        self.queue: asyncio.Queue[Detection] = asyncio.Queue()
        self.sources = []
        self._consumer: asyncio.Task | None = None

    def _emit(self, det: Detection) -> None:
        """Thread-safe hand-off from a source thread to the event loop."""
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(self.queue.put_nowait, det)

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        conf = cfg.load()
        registry = _load_registry()
        for name, klass in registry.items():
            if conf["sources"].get(name, {}).get("enabled"):
                src = klass(conf, self._emit)
                src.start()
                self.sources.append(src)
                log.info("source started: %s", name)
        if not self.sources:
            log.warning("no sources enabled — check config/skywarden.yaml")
        self._consumer = asyncio.create_task(self._consume())

    async def _consume(self) -> None:
        home = cfg.get_home()
        home_checked = time.time()
        while True:
            det = await self.queue.get()
            try:
                if time.time() - home_checked > 5:  # pick up UI home changes
                    home = cfg.get_home()
                    home_checked = time.time()
                await self.db.insert(det)
                msg = det.to_dict()
                msg["kind"] = "detection"
                # annotate with range/bearing from Home Base for the UI
                if det.has_position and home.get("set", True):
                    rng = haversine_m(home["lat"], home["lon"],
                                      det.drone_lat, det.drone_lon)
                    brg = bearing_deg(home["lat"], home["lon"],
                                      det.drone_lat, det.drone_lon)
                    msg["range_m"] = round(rng)
                    msg["bearing_deg"] = round(brg)
                    msg["compass"] = compass(brg)
                await self.hub.broadcast(msg)
            except Exception:
                log.exception("failed to process detection")

    async def stop(self) -> None:
        for src in self.sources:
            src.stop()
        if self._consumer:
            self._consumer.cancel()

    def refresh_home(self) -> None:
        # picked up by _consume on next detection via cfg cache reload
        pass
