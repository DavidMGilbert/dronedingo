"""Normalised detection record — every source produces these."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
import time


@dataclass
class Detection:
    """A single observation of a drone at a moment in time.

    Position/telemetry fields are populated from Remote ID / DroneID beacons
    (WiFi / Bluetooth). RF presence sources (RTL-SDR) leave them None and only
    set drone_id, model and rssi.
    """
    drone_id: str                       # serial / Remote ID, or RF-band token
    source: str                         # human label of the capturing source
    ts: float = field(default_factory=time.time)
    node_id: str = "warden-01"
    model: Optional[str] = None         # e.g. "DJI Mavic 3"
    # --- drone telemetry ---
    drone_lat: Optional[float] = None
    drone_lon: Optional[float] = None
    alt_msl_m: Optional[float] = None   # altitude above mean sea level
    height_agl_m: Optional[float] = None  # height above ground/launch
    speed_mps: Optional[float] = None   # horizontal speed
    vspeed_mps: Optional[float] = None  # vertical speed (+up)
    heading_deg: Optional[float] = None  # course over ground
    # --- operator (pilot) position ---
    operator_lat: Optional[float] = None
    operator_lon: Optional[float] = None
    # --- signal ---
    rssi: Optional[float] = None
    raw: dict = field(default_factory=dict)

    @property
    def has_position(self) -> bool:
        return self.drone_lat is not None and self.drone_lon is not None

    def to_dict(self) -> dict:
        return asdict(self)
