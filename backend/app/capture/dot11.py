"""802.11 management-frame and information-element parsing.

We need just enough to pull vendor-specific elements (tag 221) out of beacon /
probe-response / action frames — that is where Remote ID (OUI FA:0B:BC) and DJI
DroneID (OUI 60:60:1F) live. To also catch the NAN action-frame transport
without a full NAN implementation, ``find_vendor`` additionally byte-scans for
the vendor signature, which is robust across the beacon and NAN carriers.
"""
from __future__ import annotations
from dataclasses import dataclass, field

# Management subtypes that carry information elements after a fixed prefix.
_SUBTYPE_IE_OFFSET = {
    4: 24 + 0,    # probe request  — IEs immediately after 24-byte header
    5: 24 + 12,   # probe response — 8 ts + 2 interval + 2 caps
    8: 24 + 12,   # beacon         — same fixed fields
}


@dataclass
class Frame:
    ftype: int
    subtype: int
    src: str = ""                       # transmitter MAC (addr2)
    vendor_ies: list = field(default_factory=list)  # (oui: bytes, data: bytes)


def _mac(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


def _walk_ies(buf: bytes, start: int):
    """Yield (tag, value) for each information element from ``start``."""
    i = start
    n = len(buf)
    while i + 2 <= n:
        tag = buf[i]
        length = buf[i + 1]
        val = buf[i + 2:i + 2 + length]
        if len(val) < length:
            break
        yield tag, val
        i += 2 + length


def parse(frame: bytes) -> Frame | None:
    """Parse an 802.11 frame body (after the radiotap header)."""
    if len(frame) < 24:
        return None
    fc = frame[0]
    ftype = (fc >> 2) & 0x3
    subtype = (fc >> 4) & 0xF
    out = Frame(ftype=ftype, subtype=subtype, src=_mac(frame[10:16]))
    if ftype == 0 and subtype in _SUBTYPE_IE_OFFSET:  # management w/ IEs
        for tag, val in _walk_ies(frame, _SUBTYPE_IE_OFFSET[subtype]):
            if tag == 221 and len(val) >= 4:          # vendor specific
                out.vendor_ies.append((val[:3], val[3:]))
    return out


def find_vendor(frame: bytes, oui: bytes, vendor_type: int | None = None) -> bytes | None:
    """Return the bytes following a vendor signature anywhere in the frame.

    Catches both the beacon vendor-IE carrier and NAN action frames without a
    full NAN parser. ``vendor_type`` (e.g. 0x0D for Open Drone ID) narrows the
    match when the vendor uses a type byte after the OUI.
    """
    sig = oui if vendor_type is None else oui + bytes([vendor_type])
    idx = frame.find(sig)
    if idx < 0:
        return None
    return frame[idx + len(sig):]
