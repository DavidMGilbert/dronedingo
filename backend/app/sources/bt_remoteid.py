"""Bluetooth Remote ID capture (BT4 legacy / BT5 long range).

Uses our own HCI LE scanner (no bleak). Drones broadcasting Remote ID over
Bluetooth carry the same ASTM F3411 messages inside a Service Data AD structure
for the ASTM 16-bit UUID (0xFFFA), one 25-byte message per advertisement.
"""
from __future__ import annotations
import logging

from .base import Source
from ..models import Detection
from ..capture.hci import HciScanner, iter_ad_structures
from ..capture import odid
from .. import config as cfg

log = logging.getLogger("dronedingo")

_AD_SERVICE_DATA_16 = 0x16  # AD type: Service Data - 16-bit UUID


class BtRemoteID(Source):
    name = "bt_remoteid"

    def run(self) -> None:
        adapter = self.config["sources"]["bt_remoteid"].get("adapter", "hci0")
        dev_id = int("".join(ch for ch in adapter if ch.isdigit()) or 0)
        node_id = cfg.get_node_id()
        try:
            scanner = HciScanner(dev_id=dev_id)
        except OSError as exc:
            log.error("bt_remoteid disabled: %s", exc)
            return

        log.info("bt_remoteid scanning on %s", adapter)
        # accumulate fields per drone across successive single-message adverts
        pending: dict[str, dict] = {}
        with scanner:
            for mac, rssi, data in scanner.reports(self._stop):
                self._handle(mac, rssi, data, node_id, pending)

    def _handle(self, mac, rssi, data, node_id, pending) -> None:
        for ad_type, val in iter_ad_structures(data):
            if ad_type != _AD_SERVICE_DATA_16 or len(val) < 3:
                continue
            if val[:2] != odid.ODID_BT_SERVICE_UUID:
                continue
            # UUID(2) + app_code(1) + counter(1) + 25-byte message
            msg = val[4:29]
            fields = odid.decode_single(msg)
            if not fields:
                continue
            acc = pending.setdefault(mac, {})
            acc.update(fields)
            # emit once we have both an identity and a position
            if ("drone_lat" in acc) and (acc.get("drone_id") or "operator_lat" in acc):
                det = Detection(
                    drone_id=acc.get("drone_id") or f"RID:{mac}",
                    source="RID/BT", node_id=node_id, rssi=rssi,
                    raw={"transport": "bt", "mac": mac, "hex": val.hex()},
                    **{k: v for k, v in acc.items() if k != "drone_id"})
                self.emit(det)
