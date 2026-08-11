"""SQLite persistence for detections.

Records are append-only and timestamped for evidentiary use. Each row keeps
the decoded telemetry plus the raw payload so a capture can be reconstructed.
"""
from __future__ import annotations
import json
import time
from pathlib import Path

import aiosqlite

from .config import DATA_DIR
from .models import Detection

DB_PATH = DATA_DIR / "skywarden.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS detections (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  ts           REAL NOT NULL,
  source       TEXT,
  node_id      TEXT,
  drone_id     TEXT,
  model        TEXT,
  drone_lat    REAL, drone_lon REAL,
  alt_msl_m    REAL, height_agl_m REAL,
  speed_mps    REAL, vspeed_mps REAL, heading_deg REAL,
  operator_lat REAL, operator_lon REAL,
  rssi         REAL,
  raw          TEXT
);
CREATE INDEX IF NOT EXISTS idx_det_ts ON detections(ts);
CREATE INDEX IF NOT EXISTS idx_det_drone ON detections(drone_id, ts);
"""

_COLS = ("ts", "source", "node_id", "drone_id", "model", "drone_lat", "drone_lon",
         "alt_msl_m", "height_agl_m", "speed_mps", "vspeed_mps", "heading_deg",
         "operator_lat", "operator_lon", "rssi", "raw")


class DB:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = str(path)

    async def init(self) -> None:
        DATA_DIR.mkdir(exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

    async def insert(self, d: Detection) -> None:
        row = (d.ts, d.source, d.node_id, d.drone_id, d.model, d.drone_lat,
               d.drone_lon, d.alt_msl_m, d.height_agl_m, d.speed_mps, d.vspeed_mps,
               d.heading_deg, d.operator_lat, d.operator_lon, d.rssi,
               json.dumps(d.raw))
        placeholders = ",".join("?" * len(_COLS))
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                f"INSERT INTO detections ({','.join(_COLS)}) VALUES ({placeholders})",
                row)
            await db.commit()

    async def range(self, start: float, end: float) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM detections WHERE ts BETWEEN ? AND ? ORDER BY ts ASC",
                (start, end))
            return [dict(r) for r in await cur.fetchall()]

    async def active(self, window_s: float = 60.0) -> list[dict]:
        """All detections within the last ``window_s`` seconds."""
        return await self.range(time.time() - window_s, time.time() + 1)

    async def bounds(self) -> dict:
        """Earliest / latest timestamps on record (for the playback scrubber)."""
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT MIN(ts), MAX(ts), COUNT(*) FROM detections")
            lo, hi, n = await cur.fetchone()
            return {"min": lo, "max": hi, "count": n}

    async def events(self, since_days: int = 30, gap_s: float = 120.0,
                     limit: int = 300) -> list[dict]:
        """Collapse raw detections into per-drone sighting sessions.

        A new session starts when a drone hasn't been seen for ``gap_s``.
        """
        rows = await self.range(time.time() - since_days * 86400, time.time() + 1)
        open_sess: dict[str, dict] = {}
        sessions: list[dict] = []
        for r in rows:
            did = r["drone_id"]
            s = open_sess.get(did)
            if s and r["ts"] - s["last_seen"] <= gap_s:
                s["last_seen"] = r["ts"]
                s["count"] += 1
                s["max_alt_m"] = max(s["max_alt_m"], r["height_agl_m"] or 0)
                s["max_speed_mps"] = max(s["max_speed_mps"], r["speed_mps"] or 0)
                if r["operator_lat"] is not None:
                    s["operator_lat"] = r["operator_lat"]
                    s["operator_lon"] = r["operator_lon"]
            else:
                s = {
                    "drone_id": did, "model": r["model"], "source": r["source"],
                    "first_seen": r["ts"], "last_seen": r["ts"], "count": 1,
                    "max_alt_m": r["height_agl_m"] or 0,
                    "max_speed_mps": r["speed_mps"] or 0,
                    "operator_lat": r["operator_lat"],
                    "operator_lon": r["operator_lon"],
                }
                open_sess[did] = s
                sessions.append(s)
        sessions.sort(key=lambda x: x["last_seen"], reverse=True)
        return sessions[:limit]

    async def prune(self, retention_days: int) -> int:
        cutoff = time.time() - retention_days * 86400
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("DELETE FROM detections WHERE ts < ?", (cutoff,))
            await db.commit()
            return cur.rowcount
