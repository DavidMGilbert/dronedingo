"""WiFi Remote ID / DJI DroneID capture (2.4 / 5.8 GHz).

Requires a WiFi adapter in **monitor mode** and scapy. This is the source that
yields identity + GPS position + operator location, by decoding the ASTM F3411
"Open Drone ID" beacon that compliant drones broadcast in the clear.

    sudo ip link set wlan1 down
    sudo iw dev wlan1 set type monitor
    sudo ip link set wlan1 up

NOTE ON VALIDATION: the Open Drone ID message field offsets/scalings below
follow the ASTM F3411 spec. Decoded telemetry should be sanity-checked against
your first known real capture (a phone Remote ID app next to the receiver is an
easy reference); the full raw message hex is retained in ``raw`` for exactly
this. DJI's older proprietary DroneID uses a different layout and is flagged as
a presence hit here pending a dedicated decoder.
"""
from __future__ import annotations
import struct
import time

from .base import Source
from ..models import Detection
from .. import config as cfg

# ASTM F3411 Open Drone ID, transported in a WiFi Vendor Specific element.
_ODID_OUI = b"\xfa\x0b\xbc"
_DJI_OUI = b"\x60\x60\x1f"

# Message types (high nibble of each 25-byte message header byte).
_MSG_BASIC_ID = 0x0
_MSG_LOCATION = 0x1
_MSG_SYSTEM = 0x4
_MSG_PACK = 0xF

_UA_TYPES = {
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
    press_alt = _u16le(msg[13:15]) * 0.5 - 1000
    geo_alt = _u16le(msg[15:17]) * 0.5 - 1000
    height = _u16le(msg[17:19]) * 0.5 - 1000
    return {
        "drone_lat": round(lat, 7), "drone_lon": round(lon, 7),
        "alt_msl_m": round(geo_alt, 1), "height_agl_m": round(height, 1),
        "speed_mps": round(speed, 1), "vspeed_mps": round(vspeed, 1),
        "heading_deg": float(track % 360),
        "_press_alt": round(press_alt, 1),
    }


def _decode_basic_id(msg: bytes) -> dict:
    ua_type = msg[1] & 0x0F
    uas_id = msg[2:22].split(b"\x00", 1)[0].decode("ascii", "replace").strip()
    return {"drone_id": uas_id or None, "model": _UA_TYPES.get(ua_type)}


def _decode_system(msg: bytes) -> dict:
    op_lat = _s32le(msg[2:6]) * 1e-7
    op_lon = _s32le(msg[6:10]) * 1e-7
    if op_lat == 0 and op_lon == 0:
        return {}
    return {"operator_lat": round(op_lat, 7), "operator_lon": round(op_lon, 7)}


def _parse_message_pack(payload: bytes) -> dict:
    """Parse the sequence of 25-byte ODID messages into a merged dict."""
    out: dict = {}
    # A pack starts with header(0xF..), msg_size, qty, then qty*size messages.
    if payload and (payload[0] >> 4) == _MSG_PACK and len(payload) >= 3:
        size, qty = payload[1], payload[2]
        body = payload[3:]
        chunks = [body[i * size:(i + 1) * size] for i in range(qty)]
    else:
        chunks = [payload[i:i + 25] for i in range(0, len(payload), 25)]
    for msg in chunks:
        if len(msg) < 25:
            continue
        mtype = msg[0] >> 4
        try:
            if mtype == _MSG_LOCATION:
                out.update(_decode_location(msg))
            elif mtype == _MSG_BASIC_ID:
                out.update({k: v for k, v in _decode_basic_id(msg).items() if v})
            elif mtype == _MSG_SYSTEM:
                out.update(_decode_system(msg))
        except Exception:
            continue
    return out


class WifiRemoteID(Source):
    name = "wifi_remoteid"

    def run(self) -> None:
        try:
            from scapy.all import sniff, Dot11EltVendorSpecific  # noqa
        except Exception as exc:
            import logging
            logging.getLogger("skywarden").error(
                "wifi_remoteid disabled: scapy not available (%s)", exc)
            return

        iface = self.config["sources"]["wifi_remoteid"]["interface"]
        node_id = cfg.get_node_id()

        def handle(pkt) -> None:
            if not pkt.haslayer(Dot11EltVendorSpecific):
                return
            elt = pkt.getlayer(Dot11EltVendorSpecific)
            while elt is not None:
                info = bytes(elt.info) if hasattr(elt, "info") else b""
                oui = info[:3]
                if oui == _ODID_OUI:
                    # info = OUI(3) + vendorType(1) + counter(1) + message pack
                    fields = _parse_message_pack(info[5:])
                    if fields.get("drone_id") or "drone_lat" in fields:
                        rssi = getattr(pkt, "dBm_AntSignal", None)
                        det = Detection(
                            drone_id=fields.pop("drone_id", None) or "RID-UNKNOWN",
                            source="RID/WiFi", node_id=node_id, rssi=rssi,
                            raw={"oui": "odid", "hex": info.hex()},
                            **{k: v for k, v in fields.items()
                               if not k.startswith("_")})
                        self.emit(det)
                elif oui == _DJI_OUI:
                    rssi = getattr(pkt, "dBm_AntSignal", None)
                    self.emit(Detection(
                        drone_id="DJI-DRONEID", source="DroneID/WiFi",
                        model="DJI (DroneID)", node_id=node_id, rssi=rssi,
                        raw={"oui": "dji", "hex": info.hex(),
                             "note": "proprietary DroneID decode pending"}))
                elt = elt.payload.getlayer(Dot11EltVendorSpecific) \
                    if elt.payload else None

        # sniff blocks; stop_filter lets us exit promptly on shutdown.
        sniff(iface=iface, prn=handle, store=False,
              stop_filter=lambda _p: self._stop.is_set())
        while not self._stop.is_set():
            self.sleep(0.5)
