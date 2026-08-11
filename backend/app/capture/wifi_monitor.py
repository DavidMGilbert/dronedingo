"""Raw monitor-mode frame reader using a Linux AF_PACKET socket.

Replaces scapy's sniff(): we open a raw packet socket on the monitor interface,
receive each frame (radiotap header + 802.11 body), and hand back the signal
strength plus the parsed frame. Standard library only.
"""
from __future__ import annotations
import socket
from typing import Iterator, Optional

from . import radiotap, dot11

_ETH_P_ALL = 0x0003


class MonitorSocket:
    """Iterate 802.11 frames from a monitor-mode interface.

    Usage::

        with MonitorSocket("wlan1") as ms:
            for rssi, frame in ms.frames(stop):
                ...
    """

    def __init__(self, iface: str, timeout: float = 0.5) -> None:
        if not hasattr(socket, "AF_PACKET"):
            raise OSError("AF_PACKET is Linux-only; monitor capture unavailable "
                          "on this platform")
        self.iface = iface
        self._sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW,
                                   socket.htons(_ETH_P_ALL))
        self._sock.bind((iface, 0))
        self._sock.settimeout(timeout)

    def frames(self, stop) -> Iterator[tuple[Optional[int], "dot11.Frame", bytes]]:
        """Yield (rssi_dbm, parsed_frame, raw_dot11_bytes) until ``stop`` is set."""
        while not stop.is_set():
            try:
                buf = self._sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            rt = radiotap.parse(buf)
            if rt is None:
                continue
            body = buf[rt.length:]
            frame = dot11.parse(body)
            if frame is None:
                continue
            yield rt.dbm_signal, frame, body

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass

    def __enter__(self) -> "MonitorSocket":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
