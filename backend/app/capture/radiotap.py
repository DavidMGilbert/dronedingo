"""Minimal radiotap header parser.

Monitor-mode frames on Linux are prefixed with a radiotap header describing the
radio-level metadata (signal strength, channel, etc.). We only need the length
(to skip to the 802.11 frame) and the antenna signal in dBm.

Reference: https://www.radiotap.org/  — fields appear in bit order, each with a
defined size and alignment.
"""
from __future__ import annotations
import struct
from dataclasses import dataclass
from typing import Optional

# Radiotap "present" bit positions we care about, with (size, alignment).
_TSFT = 0
_FLAGS = 1
_RATE = 2
_CHANNEL = 3
_FHSS = 4
_DBM_ANTSIGNAL = 5
_DBM_ANTNOISE = 6
_LOCK_QUALITY = 7
_TX_ATTENUATION = 8
_DB_TX_ATTENUATION = 9
_DBM_TX_POWER = 10
_ANTENNA = 11
_DB_ANTSIGNAL = 12
_DB_ANTNOISE = 13

# (size_bytes, alignment) for each present bit, indexed by bit position.
_FIELD = {
    _TSFT: (8, 8), _FLAGS: (1, 1), _RATE: (1, 1), _CHANNEL: (4, 2),
    _FHSS: (2, 2), _DBM_ANTSIGNAL: (1, 1), _DBM_ANTNOISE: (1, 1),
    _LOCK_QUALITY: (2, 2), _TX_ATTENUATION: (2, 2), _DB_TX_ATTENUATION: (2, 2),
    _DBM_TX_POWER: (1, 1), _ANTENNA: (1, 1), _DB_ANTSIGNAL: (1, 1),
    _DB_ANTNOISE: (1, 1),
}


@dataclass
class Radiotap:
    length: int
    dbm_signal: Optional[int] = None
    channel_mhz: Optional[int] = None


def _align(offset: int, alignment: int) -> int:
    rem = offset % alignment
    return offset + (alignment - rem) if rem else offset


def parse(buf: bytes) -> Optional[Radiotap]:
    """Parse a radiotap header; return None if the buffer is too short/invalid."""
    if len(buf) < 8:
        return None
    version, _pad, length = struct.unpack_from("<BBH", buf, 0)
    if version != 0 or length < 8 or length > len(buf):
        return None

    # Read the present bitmask words (extended if the top bit is set).
    present_words = []
    off = 4
    while True:
        (word,) = struct.unpack_from("<I", buf, off)
        present_words.append(word)
        off += 4
        if not (word & (1 << 31)):
            break
        if off + 4 > length:
            break

    rt = Radiotap(length=length)
    present = present_words[0]  # first 32 fields cover everything we read
    cursor = off
    for bit in range(0, 14):
        if not (present & (1 << bit)):
            continue
        size, alignment = _FIELD[bit]
        cursor = _align(cursor, alignment)
        if cursor + size > length:
            break
        if bit == _DBM_ANTSIGNAL:
            rt.dbm_signal = struct.unpack_from("<b", buf, cursor)[0]
        elif bit == _CHANNEL:
            rt.channel_mhz = struct.unpack_from("<H", buf, cursor)[0]
        cursor += size
    return rt
