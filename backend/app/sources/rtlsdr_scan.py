"""RTL-SDR presence detection on sub-1.7 GHz bands.

Uses our own ctypes binding to librtlsdr (no pyrtlsdr). An RTL-SDR cannot see
2.4/5.8 GHz Remote ID, so this source produces no identity or GPS — it is the
backstop for non-compliant / analog drones: it sweeps the configured
control/telemetry/video bands and raises a presence hit when in-band power
rises clearly above the rolling noise floor.
"""
from __future__ import annotations
import logging

from .base import Source
from ..models import Detection
from ..capture.librtlsdr import RtlSdr
from .. import config as cfg

log = logging.getLogger("dronedingo")


class RtlSdrScan(Source):
    name = "rtlsdr_scan"

    def run(self) -> None:
        conf = self.config["sources"]["rtlsdr_scan"]
        node_id = cfg.get_node_id()
        bands = conf["bands"]
        dwell = float(conf.get("dwell_s", 0.25))
        trigger_db = float(conf.get("trigger_db", 8.0))

        try:
            sdr = RtlSdr(device_index=int(conf.get("device_index", 0)))
        except OSError as exc:
            log.error("rtlsdr_scan disabled: %s", exc)
            return

        sdr.set_sample_rate(2_400_000)
        sdr.set_gain(conf.get("gain", "auto"))
        sdr.reset_buffer()
        log.info("rtlsdr_scan sweeping %d bands", len(bands))

        floor: dict[str, float] = {}
        try:
            while not self._stop.is_set():
                for band in bands:
                    if self._stop.is_set():
                        break
                    centre = (band["start"] + band["stop"]) // 2
                    sdr.set_center_freq(centre)
                    self.sleep(dwell)
                    power_db = sdr.read_power_db()
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
                        floor[name] = base * 0.9 + power_db * 0.1
        finally:
            sdr.close()
