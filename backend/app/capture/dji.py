"""DJI DroneID decoder (proprietary WiFi beacon format).

DJI aircraft broadcast their own telemetry record in a vendor-specific element
(OUI 60:60:1F) independently of ASTM Remote ID. Two payload versions are seen
in the wild:

* **v1** — shorter record, no "home" coordinates.
* **v2** — the common modern layout, adds home lat/lon and a UUID.

Both carry the aircraft serial number, aircraft position, and — the field that
matters most for us — the **operator (pilot app) position**.

Coordinate encoding: DJI stores latitude/longitude as *radians x 1e7* signed
32-bit. Converting to degrees is therefore ``value / (1e7 * pi/180)``, i.e. the
well-known divisor 174532.925.

VALIDATION: offsets and scalings follow the publicly documented layout. Every
decode is range-checked by :func:`_plausible` and rejected if it yields
impossible values, and callers always retain the raw hex, so a mis-decode
degrades to a presence-only hit rather than fabricating telemetry. Confirm
against a known aircraft when hardware is available.
"""
from __future__ import annotations
import math
import struct
from typing import Optional

# Signed int32 radians*1e7 -> degrees.
_RAD_1E7_TO_DEG = 1e7 * math.pi / 180.0   # 174532.925...

# Payload record types.
_PKT_FLIGHT_INFO = 0x10

# Known aircraft type codes (partial — unknown codes fall back to "DJI aircraft").
DEVICE_TYPES = {
    0: "DJI Inspire 1", 1: "DJI Phantom 3 Series", 2: "DJI Phantom 3 Std",
    3: "DJI M100", 4: "DJI ACEONE", 5: "DJI WKM", 6: "DJI NAZA",
    7: "DJI A2", 8: "DJI A3", 9: "DJI Phantom 4", 10: "DJI MG1",
    11: "DJI M600", 12: "DJI Phantom 3 4K", 13: "DJI Mavic Pro",
    14: "DJI Inspire 2", 15: "DJI Phantom 4 Pro", 16: "DJI N3",
    17: "DJI Spark", 18: "DJI Mavic Air", 19: "DJI Mavic 2",
    20: "DJI Phantom 4 RTK", 21: "DJI Mavic Mini", 22: "DJI Matrice 200",
    23: "DJI Mavic Air 2", 24: "DJI Matrice 300", 25: "DJI FPV",
    26: "DJI Mini 2", 27: "DJI Mavic 3", 28: "DJI Mini SE",
    29: "DJI Mavic 3 Classic", 30: "DJI Mini 3 Pro", 31: "DJI Avata",
}


def _deg(raw: int) -> float:
    return raw / _RAD_1E7_TO_DEG


def _plausible(lat: Optional[float], lon: Optional[float]) -> bool:
    """Reject decodes that produce impossible coordinates."""
    if lat is None or lon is None:
        return False
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return False
    return not (abs(lat) < 1e-6 and abs(lon) < 1e-6)   # 0,0 == "no fix"


def _clean_serial(b: bytes) -> str:
    s = b.split(b"\x00", 1)[0]
    return "".join(chr(c) for c in s if 32 <= c < 127).strip()


def _decode_v2(p: bytes) -> dict:
    """Modern DJI flight-info record (>= 78 bytes of payload)."""
    if len(p) < 78:
        return {}
    seq, state = struct.unpack_from("<HH", p, 0)
    serial = _clean_serial(p[4:20])
    lon_r, lat_r = struct.unpack_from("<ii", p, 20)
    alt, height, v_north, v_east, v_up = struct.unpack_from("<hhhhh", p, 28)
    pitch, roll, yaw = struct.unpack_from("<hhh", p, 38)
    app_lat_r, app_lon_r = struct.unpack_from("<ii", p, 44)
    home_lon_r, home_lat_r = struct.unpack_from("<ii", p, 52)
    device_type = p[60]

    lat, lon = _deg(lat_r), _deg(lon_r)
    if not _plausible(lat, lon):
        return {}

    speed = math.hypot(v_north, v_east) / 10.0        # decimetres/s -> m/s
    heading = (math.degrees(math.atan2(v_east, v_north)) + 360.0) % 360.0
    out = {
        "drone_id": serial or None,
        "model": DEVICE_TYPES.get(device_type, "DJI aircraft"),
        "drone_lat": round(lat, 7), "drone_lon": round(lon, 7),
        "alt_msl_m": round(alt / 10.0, 1),
        "height_agl_m": round(height / 10.0, 1),
        "speed_mps": round(speed, 1),
        "vspeed_mps": round(v_up / 10.0, 1),
        "heading_deg": round(heading, 1),
        "_seq": seq, "_state": state, "_yaw": yaw,
        "_pitch": pitch, "_roll": roll,
    }
    app_lat, app_lon = _deg(app_lat_r), _deg(app_lon_r)
    if _plausible(app_lat, app_lon):
        out["operator_lat"] = round(app_lat, 7)
        out["operator_lon"] = round(app_lon, 7)
    home_lat, home_lon = _deg(home_lat_r), _deg(home_lon_r)
    if _plausible(home_lat, home_lon):
        out["_home_lat"] = round(home_lat, 7)
        out["_home_lon"] = round(home_lon, 7)
    return out


def _decode_v1(p: bytes) -> dict:
    """Older/shorter DJI record: serial, position, operator, no home coords."""
    if len(p) < 62:
        return {}
    serial = _clean_serial(p[0:16])
    lon_r, lat_r = struct.unpack_from("<ii", p, 16)
    alt, height, v_north, v_east, v_up = struct.unpack_from("<hhhhh", p, 24)
    app_lat_r, app_lon_r = struct.unpack_from("<ii", p, 40)

    lat, lon = _deg(lat_r), _deg(lon_r)
    if not _plausible(lat, lon):
        return {}
    speed = math.hypot(v_north, v_east) / 10.0
    heading = (math.degrees(math.atan2(v_east, v_north)) + 360.0) % 360.0
    out = {
        "drone_id": serial or None, "model": "DJI aircraft",
        "drone_lat": round(lat, 7), "drone_lon": round(lon, 7),
        "alt_msl_m": round(alt / 10.0, 1),
        "height_agl_m": round(height / 10.0, 1),
        "speed_mps": round(speed, 1), "vspeed_mps": round(v_up / 10.0, 1),
        "heading_deg": round(heading, 1),
    }
    app_lat, app_lon = _deg(app_lat_r), _deg(app_lon_r)
    if _plausible(app_lat, app_lon):
        out["operator_lat"] = round(app_lat, 7)
        out["operator_lon"] = round(app_lon, 7)
    return out


def decode(payload: bytes) -> dict:
    """Decode the bytes following the DJI OUI in a vendor-specific element.

    Returns a dict of Detection fields (empty if this is not a decodable
    flight-info record). Keys prefixed with ``_`` are extra context for the raw
    log rather than Detection fields.
    """
    if len(payload) < 4:
        return {}
    # Locate the flight-info record: normally  <type=0x10> <ver> <len> <body...>
    idx = payload.find(bytes([_PKT_FLIGHT_INFO]))
    if idx < 0 or idx + 3 > len(payload):
        return {}
    version = payload[idx + 1]
    body = payload[idx + 3:]
    result = _decode_v2(body) if version >= 2 else _decode_v1(body)
    if result:
        result["_dji_version"] = version
    return result
