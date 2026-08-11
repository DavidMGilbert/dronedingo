"""WiFi Remote ID / DJI DroneID capture (2.4 / 5.8 GHz).

Uses our own raw monitor-mode reader and 802.11 parser (no scapy). This is the
source that yields identity + GPS position + operator location by decoding the
ASTM F3411 "Open Drone ID" beacon that compliant drones broadcast in the clear.

Put the adapter in monitor mode first (deploy/monitor-mode.sh):
    sudo ip link set wlan1 down
    sudo iw dev wlan1 set type monitor
    sudo ip link set wlan1 up
"""
from __future__ import annotations
import logging

from .base import Source
from ..models import Detection
from ..capture.wifi_monitor import MonitorSocket
from ..capture import dot11, odid, dji
from .. import config as cfg

log = logging.getLogger("skywarden")


class WifiRemoteID(Source):
    name = "wifi_remoteid"

    def run(self) -> None:
        iface = self.config["sources"]["wifi_remoteid"]["interface"]
        node_id = cfg.get_node_id()
        try:
            sock = MonitorSocket(iface)
        except OSError as exc:
            log.error("wifi_remoteid disabled: %s", exc)
            return

        log.info("wifi_remoteid capturing on %s", iface)
        with sock:
            for rssi, frame, raw in sock.frames(self._stop):
                self._handle(frame, raw, rssi, node_id)

    def _handle(self, frame: "dot11.Frame", raw: bytes, rssi, node_id: str) -> None:
        # Open Drone ID — beacon vendor IE or NAN action frame.
        pack = dot11.find_vendor(raw, odid.ODID_OUI, odid.ODID_VENDOR_TYPE)
        if pack is not None:
            fields = odid.decode_pack(pack[1:])  # skip 1-byte message counter
            if fields.get("drone_id") or "drone_lat" in fields:
                det = Detection(
                    drone_id=fields.pop("drone_id", None) or "RID-UNKNOWN",
                    source="RID/WiFi", node_id=node_id, rssi=rssi,
                    raw={"oui": "odid", "mac": frame.src, "hex": raw.hex()},
                    **fields)
                self.emit(det)
            return
        # DJI proprietary DroneID.
        dji_payload = dot11.find_vendor(raw, odid.DJI_OUI)
        if dji_payload is not None:
            fields = dji.decode(dji_payload)
            extra = {k: v for k, v in fields.items() if k.startswith("_")}
            fields = {k: v for k, v in fields.items() if not k.startswith("_")}
            if fields.get("drone_lat") is not None:
                self.emit(Detection(
                    drone_id=fields.pop("drone_id", None) or f"DJI:{frame.src}",
                    source="DroneID/WiFi", node_id=node_id, rssi=rssi,
                    raw={"oui": "dji", "mac": frame.src, "hex": raw.hex(), **extra},
                    **fields))
            else:
                # Undecodable record — still worth logging as a presence hit.
                self.emit(Detection(
                    drone_id=f"DJI:{frame.src}", source="DroneID/WiFi",
                    model="DJI (unidentified)", node_id=node_id, rssi=rssi,
                    raw={"oui": "dji", "mac": frame.src, "hex": raw.hex(),
                         "note": "DJI record present but not decodable"}))
