"""In-house capture primitives.

These modules replace third-party GPL libraries (scapy, pyrtlsdr) with our own
implementations so the product carries no copyleft dependencies:

* ``radiotap``   — radiotap header parser (RSSI, channel, flags)
* ``dot11``      — 802.11 frame + information-element parser
* ``wifi_monitor`` — raw AF_PACKET monitor-mode frame reader (Linux)
* ``librtlsdr``  — ctypes binding to the system librtlsdr shared object
* ``hci``        — Bluetooth HCI LE advertisement scanner (Linux)

All are pure-Python and standard-library only, so they add nothing to install
and run comfortably on a Raspberry Pi.
"""
