"""Thin ctypes binding to the system librtlsdr shared library.

Replaces the pyrtlsdr package (GPL) with a direct binding to the librtlsdr .so,
which is installed on the Pi via apt (`librtlsdr0`) and never redistributed by
us. Only the handful of calls needed for synchronous band-power sampling are
bound. Standard library only — power is computed with a squares lookup table so
numpy is not required.
"""
from __future__ import annotations
import ctypes
import ctypes.util
from ctypes import c_void_p, c_int, c_uint32, c_ubyte, POINTER, byref

# Precomputed (sample - midpoint)^2 for unsigned 8-bit I/Q, for fast power calc.
_MID = 127.4
_SQ = [(i - _MID) ** 2 for i in range(256)]


def _load_lib():
    for name in ("rtlsdr", "librtlsdr.so.0", "librtlsdr.so", "librtlsdr"):
        path = ctypes.util.find_library(name) or name
        try:
            return ctypes.CDLL(path)
        except OSError:
            continue
    raise OSError("librtlsdr not found — install it (apt install librtlsdr0)")


class RtlSdr:
    """Minimal synchronous RTL-SDR reader."""

    def __init__(self, device_index: int = 0) -> None:
        self._lib = _load_lib()
        self._bind()
        self._dev = c_void_p()
        if self._lib.rtlsdr_open(byref(self._dev), c_uint32(device_index)) != 0:
            raise OSError(f"could not open RTL-SDR device index {device_index}")

    def _bind(self) -> None:
        L = self._lib
        L.rtlsdr_open.argtypes = [POINTER(c_void_p), c_uint32]
        L.rtlsdr_close.argtypes = [c_void_p]
        L.rtlsdr_set_sample_rate.argtypes = [c_void_p, c_uint32]
        L.rtlsdr_set_center_freq.argtypes = [c_void_p, c_uint32]
        L.rtlsdr_set_tuner_gain_mode.argtypes = [c_void_p, c_int]
        L.rtlsdr_set_tuner_gain.argtypes = [c_void_p, c_int]
        L.rtlsdr_set_agc_mode.argtypes = [c_void_p, c_int]
        L.rtlsdr_reset_buffer.argtypes = [c_void_p]
        L.rtlsdr_read_sync.argtypes = [c_void_p, c_void_p, c_int, POINTER(c_int)]
        L.rtlsdr_get_device_count.restype = c_uint32

    # --- configuration ---
    def set_sample_rate(self, rate: int) -> None:
        self._lib.rtlsdr_set_sample_rate(self._dev, c_uint32(int(rate)))

    def set_center_freq(self, freq: int) -> None:
        self._lib.rtlsdr_set_center_freq(self._dev, c_uint32(int(freq)))

    def set_gain(self, gain) -> None:
        if gain == "auto":
            self._lib.rtlsdr_set_tuner_gain_mode(self._dev, 0)  # 0 = auto
            self._lib.rtlsdr_set_agc_mode(self._dev, 1)
        else:
            self._lib.rtlsdr_set_tuner_gain_mode(self._dev, 1)  # 1 = manual
            self._lib.rtlsdr_set_tuner_gain(self._dev, int(float(gain) * 10))

    def reset_buffer(self) -> None:
        self._lib.rtlsdr_reset_buffer(self._dev)

    # --- sampling ---
    def read_power_db(self, n_samples: int = 16384) -> float:
        """Read IQ samples and return mean power in dB (relative units)."""
        import math
        n_bytes = n_samples * 2
        buf = (c_ubyte * n_bytes)()
        n_read = c_int(0)
        rc = self._lib.rtlsdr_read_sync(self._dev, buf, n_bytes, byref(n_read))
        if rc != 0 or n_read.value <= 0:
            return -120.0
        total = 0.0
        count = n_read.value
        for i in range(count):
            total += _SQ[buf[i]]
        mean = total / count if count else 1e-9
        return 10.0 * math.log10(mean + 1e-9)

    def close(self) -> None:
        try:
            self._lib.rtlsdr_close(self._dev)
        except Exception:
            pass


def device_count() -> int:
    try:
        return int(_load_lib().rtlsdr_get_device_count())
    except Exception:
        return 0
