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
from .alerts import Alerter
from .geo import haversine_m, bearing_deg, compass
from . import config as cfg

log = logging.getLogger("dronedingo")

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
        self.alerter = Alerter(cfg.load())

    def reload_alerter(self) -> None:
        """Rebuild the alerter after a settings change from the UI."""
        self.alerter = Alerter(cfg.load())

    def source_running(self, name: str) -> bool:
        return any(getattr(s, "name", None) == name for s in self.sources)

    def start_source(self, name: str) -> bool:
        """Start one capture source live (e.g. the simulator for Demo mode)."""
        if self.loop is None or self.source_running(name):
            return self.source_running(name)
        klass = _load_registry().get(name)
        if klass is None:
            return False
        src = klass(cfg.load(), self._emit)
        src.start()
        self.sources.append(src)
        log.info("source started (live): %s", name)
        return True

    def stop_source(self, name: str) -> bool:
        """Stop and remove one running capture source live."""
        stopped = False
        for src in list(self.sources):
            if getattr(src, "name", None) == name:
                src.stop()
                self.sources.remove(src)
                stopped = True
                log.info("source stopped (live): %s", name)
        return stopped

    def _emit(self, det: Detection) -> None:
        """Thread-safe hand-off from a source thread to the event loop."""
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(self.queue.put_nowait, det)

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        # Clean out any demo rows written before demo traffic became non-persistent.
        try:
            purged = await self.db.purge_simulated()
            if purged:
                log.info("purged %d stale demo detection(s) from the DB", purged)
        except Exception:
            log.warning("could not purge stale demo rows", exc_info=True)
        conf = cfg.load()
        registry = _load_registry()
        for name, klass in registry.items():
            if conf["sources"].get(name, {}).get("enabled"):
                src = klass(conf, self._emit)
                src.start()
                self.sources.append(src)
                log.info("source started: %s", name)
        if not self.sources:
            log.warning("no sources enabled — check config/dronedingo.yaml")
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
                # Demo-mode traffic is shown live and can drive test alerts, but
                # is never written to the evidence DB (keeps history/logs clean).
                if not det.simulated:
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
                self.alerter.consider(msg)   # non-blocking; dispatches off-thread
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
