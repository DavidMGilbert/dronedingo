"""Alert delivery — phone push via ntfy, plus a generic webhook.

Design goal: an alert the farmer will still act on in week three. That means
**one notification per sighting**, not one per beacon. A drone broadcasts
several times a second; we therefore alert once when a contact first breaches
the alert ring, then stay quiet for that contact until it has been gone for
``resight_after_s``.

Delivery is fire-and-forget on a worker thread so nothing can stall capture.
"""
from __future__ import annotations
import json
import logging
import threading
import time
import urllib.request
from datetime import datetime, time as dtime

log = logging.getLogger("dronedingo")

_TIMEOUT = 8.0


def _parse_quiet(spec: str | None):
    """Parse a "HH:MM-HH:MM" quiet-hours window."""
    if not spec:
        return None
    try:
        a, b = spec.split("-")
        sh, sm = (int(x) for x in a.split(":"))
        eh, em = (int(x) for x in b.split(":"))
        return dtime(sh, sm), dtime(eh, em)
    except Exception:
        log.warning("could not parse alerts.quiet_hours=%r — ignoring", spec)
        return None


def _in_window(now: dtime, start: dtime, end: dtime) -> bool:
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end       # window crosses midnight


class Alerter:
    def __init__(self, conf: dict) -> None:
        a = conf.get("alerts") or {}
        self.topic = a.get("ntfy_topic")
        self.server = (a.get("ntfy_server") or "https://ntfy.sh").rstrip("/")
        self.webhook = a.get("webhook_url")
        self.quiet = _parse_quiet(a.get("quiet_hours"))
        self.quiet_suppresses = bool(a.get("quiet_hours_suppress", False))
        self.resight_after_s = float(a.get("resight_after_s", 300))
        self.ring_m = float(a.get("alert_ring_m")
                            or (conf.get("map", {}).get("range_rings_m") or [250])[0])
        self._last_alert: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.topic or self.webhook)

    def _should_fire(self, drone_id: str, range_m: float | None) -> bool:
        if range_m is None or range_m > self.ring_m:
            return False
        now = time.time()
        with self._lock:
            last = self._last_alert.get(drone_id, 0.0)
            if now - last < self.resight_after_s:
                return False
            self._last_alert[drone_id] = now
        return True

    def consider(self, det: dict) -> None:
        """Evaluate a detection and dispatch an alert if it warrants one."""
        if not self.enabled:
            return
        if not self._should_fire(det.get("drone_id", "?"), det.get("range_m")):
            return
        if self.quiet and self.quiet_suppresses and \
                _in_window(datetime.now().time(), *self.quiet):
            log.info("alert suppressed by quiet hours: %s", det.get("drone_id"))
            return
        threading.Thread(target=self._dispatch, args=(det,),
                         name="alert-send", daemon=True).start()

    # ------------------------------------------------------------------
    def _compose(self, det: dict) -> tuple[str, str]:
        model = det.get("model") or "Drone"
        rng = det.get("range_m")
        compass = det.get("compass") or ""
        title = f"{model} detected — {rng} m {compass}".strip()
        lines = [
            f"ID: {det.get('drone_id')}",
            f"Range: {rng} m {compass}".strip(),
        ]
        if det.get("height_agl_m") is not None:
            lines.append(f"Height: {round(det['height_agl_m'])} m")
        if det.get("speed_mps") is not None:
            lines.append(f"Speed: {round(det['speed_mps'], 1)} m/s")
        if det.get("operator_lat") is not None:
            lines.append(f"Operator: {det['operator_lat']:.5f}, "
                         f"{det['operator_lon']:.5f}")
        lines.append(f"Source: {det.get('source')}")
        return title, "\n".join(lines)

    def _dispatch(self, det: dict) -> None:
        title, body = self._compose(det)
        if self.topic:
            try:
                self._send_ntfy(title, body, det)
            except Exception as exc:
                log.warning("ntfy delivery failed: %s", exc)
        if self.webhook:
            try:
                self._send_webhook(det)
            except Exception as exc:
                log.warning("webhook delivery failed: %s", exc)

    def _send_ntfy(self, title: str, body: str, det: dict) -> None:
        url = f"{self.server}/{self.topic}"
        headers = {
            "Title": title,
            "Priority": "high",
            "Tags": "rotating_light",
            "Content-Type": "text/plain; charset=utf-8",
        }
        # Deep-link the operator position to a map when we have one.
        if det.get("operator_lat") is not None:
            headers["Actions"] = (
                "view, Operator location, "
                f"https://www.openstreetmap.org/?mlat={det['operator_lat']}"
                f"&mlon={det['operator_lon']}#map=17/"
                f"{det['operator_lat']}/{det['operator_lon']}"
            )
        req = urllib.request.Request(url, data=body.encode("utf-8"),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            resp.read()
        log.info("alert sent: %s", title)

    def _send_webhook(self, det: dict) -> None:
        req = urllib.request.Request(
            self.webhook, data=json.dumps(det).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            resp.read()

    def test(self) -> dict:
        """Send a test notification; returns a result dict for the API."""
        if not self.enabled:
            return {"ok": False, "error": "No ntfy topic or webhook configured."}
        try:
            self._send_ntfy("DroneDingo test alert",
                            "If you can read this, alerts are working.", {}) \
                if self.topic else None
            if self.webhook:
                self._send_webhook({"test": True})
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
