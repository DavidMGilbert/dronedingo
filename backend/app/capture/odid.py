"""Open Drone ID (ASTM F3411) message decoding — shared by WiFi and Bluetooth.

The same 25-byte message format is carried over every transport, so both the
WiFi and BT sources decode with these functions. Field offsets/scalings follow
the ASTM F3411 specification; validate against a known real capture on first
hardware (a phone Remote ID app next to the receiver is an easy reference). The
raw message hex is always retained by callers for exactly this.
"""
from __future__ import annotations
import struct

# Vendor signatures.
ODID_OUI = b"\xfa\x0b\xbc"        # ASTM Remote ID (WiFi vendor IE / NAN)
ODID_VENDOR_TYPE = 0x0D
DJI_OUI = b"\x60\x60\x1f"         # DJI proprietary DroneID
ODID_BT_SERVICE_UUID = b"\xfa\xff"  # 0xFFFA little-endian (ASTM), BT service data

# Message types (high nibble of message header byte).
MSG_BASIC_ID = 0x0
MSG_LOCATION = 0x1
MSG_SYSTEM = 0x4
MSG_PACK = 0xF

UA_TYPES = {
    0: "Unknown", 1: "Fixed Wing", 2: "Multirotor", 3: "Gyroplane",
    4: "VTOL", 5: "Ornithopter", 6: "Glider", 7: "Kite",
    8: "Free Balloon", 9: "Captive Balloon", 10: "Airship",
    11: "Parachute", 12: "Rocket", 13: "Tethered", 14: "Ground Obstacle",
}


def _s32le(b: bytes) -> int:
    return struct.unpack("<i", b)[0]


def _u16le(b: bytes) -> int:
    return struct.unpack("<H", b)[0]


def _decode_location(msg: bytes) -> dict:
    status = msg[1]
    ew_flag = (status >> 1) & 0x1
    mult_flag = status & 0x1
    track = msg[2] + (180 if ew_flag else 0)
    enc_speed = msg[3]
    speed = enc_speed * 0.25 if not mult_flag else (enc_speed * 0.75) + (255 * 0.25)
    vspeed = struct.unpack("<b", msg[4:5])[0] * 0.5
    lat = _s32le(msg[5:9]) * 1e-7
    lon = _s32le(msg[9:13]) * 1e-7
    geo_alt = _u16le(msg[15:17]) * 0.5 - 1000
    height = _u16le(msg[17:19]) * 0.5 - 1000
    return {
        "drone_lat": round(lat, 7), "drone_lon": round(lon, 7),
        "alt_msl_m": round(geo_alt, 1), "height_agl_m": round(height, 1),
        "speed_mps": round(speed, 1), "vspeed_mps": round(vspeed, 1),
        "heading_deg": float(track % 360),
    }


def _decode_basic_id(msg: bytes) -> dict:
    ua_type = msg[1] & 0x0F
    uas_id = msg[2:22].split(b"\x00", 1)[0].decode("ascii", "replace").strip()
    return {"drone_id": uas_id or None, "model": UA_TYPES.get(ua_type)}


def _decode_system(msg: bytes) -> dict:
    op_lat = _s32le(msg[2:6]) * 1e-7
    op_lon = _s32le(msg[6:10]) * 1e-7
    if op_lat == 0 and op_lon == 0:
        return {}
    return {"operator_lat": round(op_lat, 7), "operator_lon": round(op_lon, 7)}


def _decode_one(msg: bytes) -> dict:
    if len(msg) < 25:
        return {}
    mtype = msg[0] >> 4
    try:
        if mtype == MSG_LOCATION:
            return _decode_location(msg)
        if mtype == MSG_BASIC_ID:
            return {k: v for k, v in _decode_basic_id(msg).items() if v}
        if mtype == MSG_SYSTEM:
            return _decode_system(msg)
    except Exception:
        return {}
    return {}


def decode_pack(payload: bytes) -> dict:
    """Decode a message pack (0xF header) or a raw run of 25-byte messages."""
    out: dict = {}
    if payload and (payload[0] >> 4) == MSG_PACK and len(payload) >= 3:
        size, qty = payload[1], payload[2]
        body = payload[3:]
        chunks = [body[i * size:(i + 1) * size] for i in range(qty)]
    else:
        chunks = [payload[i:i + 25] for i in range(0, len(payload), 25)]
    for msg in chunks:
        out.update(_decode_one(msg))
    return out


def decode_single(msg: bytes) -> dict:
    """Decode a single 25-byte message (Bluetooth carries one per advert)."""
    return _decode_one(msg)
