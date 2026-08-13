"""Synthetic drone traffic.

Generates believable Remote ID style contacts flying around the configured
Home Base so the full UI (live map, telemetry, tracks, playback) works with no
hardware attached. Each synthetic drone has an operator at a fixed field-edge
position, exactly as a real DroneID capture would report.
"""
from __future__ import annotations
import math
import random
import time

from .base import Source
from ..models import Detection
from ..geo import offset_m, bearing_deg, haversine_m
from .. import config as cfg


class _Drone:
    def __init__(self, drone_id, model, home, waypoints_m, operator_m,
                 cruise_mps, cruise_alt):
        self.id = drone_id
        self.model = model
        hlat, hlon = home["lat"], home["lon"]
        self.ground_msl = 80.0
        self.waypoints = [offset_m(hlat, hlon, n, e) for (n, e) in waypoints_m]
        self.op_lat, self.op_lon = offset_m(hlat, hlon, *operator_m)
        self.cruise = cruise_mps
        self.alt = cruise_alt
        self.target_alt = cruise_alt
        self.i = 0
        self.lat, self.lon = self.waypoints[0]
        self.heading = 0.0
        self.vspeed = 0.0

    def step(self, dt: float) -> None:
        tlat, tlon = self.waypoints[self.i]
        dist = haversine_m(self.lat, self.lon, tlat, tlon)
        if dist < 6.0:  # reached waypoint -> next, occasionally change height
            self.i = (self.i + 1) % len(self.waypoints)
            if random.random() < 0.4:
                self.target_alt = random.uniform(30, 110)
            return
        brg = bearing_deg(self.lat, self.lon, tlat, tlon)
        # jitter the heading slightly so tracks look organic
        self.heading = brg + random.uniform(-3, 3)
        span = self.cruise * dt
        self.lat, self.lon = offset_m(
            self.lat, self.lon,
            span * math.cos(math.radians(self.heading)),
            span * math.sin(math.radians(self.heading)))
        # ease altitude toward target
        da = self.target_alt - self.alt
        self.vspeed = max(-3.0, min(3.0, da * 0.15))
        self.alt += self.vspeed * dt

    def detection(self, node_id: str, home) -> Detection:
        d_home = haversine_m(home["lat"], home["lon"], self.lat, self.lon)
        rssi = -40 - 0.03 * d_home + random.uniform(-2, 2)  # weaker with distance
        return Detection(
            drone_id=self.id, source="RID/WiFi (sim)", model=self.model,
            node_id=node_id, drone_lat=round(self.lat, 6), drone_lon=round(self.lon, 6),
            alt_msl_m=round(self.alt + self.ground_msl, 1),
            height_agl_m=round(self.alt, 1),
            speed_mps=round(self.cruise, 1), vspeed_mps=round(self.vspeed, 1),
            heading_deg=round(self.heading % 360, 1),
            operator_lat=round(self.op_lat, 6), operator_lon=round(self.op_lon, 6),
            rssi=round(rssi, 1), raw={"sim": True, "protocol": "ASTM-F3411"})


class Simulator(Source):
    name = "simulator"

    def _build(self):
        home = cfg.get_home()
        node_id = cfg.get_node_id()
        # A survey drone tracing the perimeter, and one loitering by the yard.
        drones = [
            _Drone(
                "1581F5FKD2440100SIM", "DJI Mavic 3",
                home,
                waypoints_m=[(400, -400), (400, 400), (-400, 400), (-400, -400)],
                operator_m=(-460, -430), cruise_mps=11.0, cruise_alt=70.0),
            _Drone(
                "SIM-AUTEL-EVO-0079", "Autel EVO II",
                home,
                waypoints_m=[(60, 120), (-40, 180), (-120, 60), (-30, -20)],
                operator_m=(230, 300), cruise_mps=5.0, cruise_alt=40.0),
        ]
        return drones, node_id, home

    def run(self) -> None:
        drones, node_id, home = self._build()
        last = time.time()
        # Emits live contacts only — these are flagged simulated (raw.sim) and are
        # never persisted, so demo mode leaves no history/log residue.
        while not self._stop.is_set():
            now = time.time()
            dt = min(2.0, now - last)
            last = now
            for d in drones:
                d.step(dt)
                self.emit(d.detection(node_id, home))
            self.sleep(1.0)
