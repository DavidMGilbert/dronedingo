"""RTL-SDR presence detection on sub-1.7 GHz bands.

An RTL-SDR cannot see 2.4/5.8 GHz Remote ID, so this source does NOT produce
identity or GPS. It is the backstop for *non-compliant / analog* drones: it
sweeps the configured control/telemetry/video bands and raises a presence hit
when in-band power rises clearly above the rolling noise floor.
"""
from __future__ import annotations
import time

from .base import Source
from ..models import Detection
from .. import config as cfg


class RtlSdrScan(Source):
    name = "rtlsdr_scan"

    def run(self) -> None:
        try:
            import numpy as np
            from rtlsdr import RtlSdr
        except Exception as exc:
            import logging
            logging.getLogger("skywarden").error(
                "rtlsdr_scan disabled: pyrtlsdr/numpy not available (%s)", exc)
            return

        conf = self.config["sources"]["rtlsdr_scan"]
        node_id = cfg.get_node_id()
        bands = conf["bands"]
        dwell = float(conf.get("dwell_s", 0.25))
        trigger_db = float(conf.get("trigger_db", 8.0))
        sample_rate = 2_400_000
        n = 256 * 1024

        sdr = RtlSdr(device_index=int(conf.get("device_index", 0)))
        sdr.sample_rate = sample_rate
        gain = conf.get("gain", "auto")
        sdr.gain = gain if gain == "auto" else float(gain)

        # per-band rolling noise floor estimate (dB)
        floor: dict[str, float] = {}
        try:
            while not self._stop.is_set():
                for band in bands:
                    if self._stop.is_set():
                        break
                    centre = (band["start"] + band["stop"]) / 2
                    sdr.center_freq = centre
                    self.sleep(dwell)
                    samples = sdr.read_samples(n)
                    power_db = 10.0 * np.log10(np.mean(np.abs(samples) ** 2) + 1e-12)
                    name = band["name"]
                    base = floor.get(name)
                    if base is None:
                        floor[name] = power_db
                        continue
                    if power_db - base >= trigger_db:
                        self.emit(Detection(
                            drone_id=f"RF:{name}", source="RF/RTL-SDR",
                            model="Unidentified RF emitter", node_id=node_id,
                            rssi=round(power_db, 1),
                            raw={"band": name, "center_hz": centre,
                                 "floor_db": round(base, 1),
                                 "delta_db": round(power_db - base, 1)}))
                    else:
                        # slow adaptation of the noise floor toward quiet periods
                        floor[name] = base * 0.9 + power_db * 0.1
        finally:
            try:
                sdr.close()
            except Exception:
                pass
