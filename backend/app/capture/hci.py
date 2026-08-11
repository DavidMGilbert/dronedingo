"""Bluetooth LE passive scanner over a raw HCI socket (BlueZ / Linux).

Replaces the bleak dependency with a direct HCI binding and, in doing so, adds
the Bluetooth Remote ID transport. We drive the controller with the minimum HCI
commands (set scan parameters -> enable scan) and parse LE Advertising Report
events. Passive scanning is used, so the receiver never transmits scan requests.
"""
from __future__ import annotations
import socket
import struct
from typing import Iterator

_SOL_HCI = 0
_HCI_FILTER = 2

# HCI opcodes (OGF 0x08 = LE Controller).
_OP_LE_SET_SCAN_PARAMS = 0x200B
_OP_LE_SET_SCAN_ENABLE = 0x200C

_HCI_EVENT_PKT = 0x04
_EVT_LE_META = 0x3E
_SUBEVT_ADV_REPORT = 0x02


def _available() -> bool:
    return hasattr(socket, "AF_BLUETOOTH") and hasattr(socket, "BTPROTO_HCI")


def _cmd(opcode: int, params: bytes = b"") -> bytes:
    return struct.pack("<BHB", 0x01, opcode, len(params)) + params


class HciScanner:
    def __init__(self, dev_id: int = 0, timeout: float = 0.5) -> None:
        if not _available():
            raise OSError("AF_BLUETOOTH/BTPROTO_HCI unavailable on this platform")
        self._sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW,
                                   socket.BTPROTO_HCI)
        self._sock.bind((dev_id,))
        self._sock.settimeout(timeout)
        # Receive all HCI event packets.
        flt = struct.pack("<IIIH", 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0)
        self._sock.setsockopt(_SOL_HCI, _HCI_FILTER, flt)

    def _start(self) -> None:
        # passive scan (0x00); interval/window 0x0010; public own addr; no filter
        params = struct.pack("<BHHBB", 0x00, 0x0010, 0x0010, 0x00, 0x00)
        self._sock.send(_cmd(_OP_LE_SET_SCAN_PARAMS, params))
        # enable=1, filter_duplicates=0
        self._sock.send(_cmd(_OP_LE_SET_SCAN_ENABLE, struct.pack("<BB", 0x01, 0x00)))

    def _stop_scan(self) -> None:
        try:
            self._sock.send(_cmd(_OP_LE_SET_SCAN_ENABLE, struct.pack("<BB", 0x00, 0x00)))
        except Exception:
            pass

    def reports(self, stop) -> Iterator[tuple[str, int, bytes]]:
        """Yield (mac, rssi, adv_data) for each LE advertising report."""
        self._start()
        try:
            while not stop.is_set():
                try:
                    pkt = self._sock.recv(258)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if len(pkt) < 3 or pkt[0] != _HCI_EVENT_PKT:
                    continue
                if pkt[1] != _EVT_LE_META:
                    continue
                sub = pkt[3]
                if sub != _SUBEVT_ADV_REPORT:
                    continue
                num = pkt[4]
                off = 5
                for _ in range(num):
                    if off + 9 > len(pkt):
                        break
                    # evt_type(1) addr_type(1) addr(6) data_len(1)
                    addr = pkt[off + 2:off + 8][::-1]
                    dlen = pkt[off + 8]
                    data = pkt[off + 9:off + 9 + dlen]
                    rssi = struct.unpack("<b", pkt[off + 9 + dlen:off + 10 + dlen])[0] \
                        if off + 9 + dlen < len(pkt) else 0
                    mac = ":".join(f"{b:02x}" for b in addr)
                    yield mac, rssi, data
                    off += 9 + dlen + 1
        finally:
            self._stop_scan()

    def close(self) -> None:
        self._stop_scan()
        try:
            self._sock.close()
        except Exception:
            pass


def iter_ad_structures(data: bytes) -> Iterator[tuple[int, bytes]]:
    """Yield (ad_type, value) from a BLE advertising data payload."""
    i = 0
    while i < len(data):
        length = data[i]
        if length == 0 or i + 1 + length > len(data):
            break
        yield data[i + 1], data[i + 2:i + 1 + length]
        i += 1 + length
