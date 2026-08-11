<div align="center">

# 🛡️ DroneDingo

**Know what's in your sky.**

Passive drone detection, identification & airspace-logging appliance
for property and perimeter security.

</div>

---

DroneDingo is a Raspberry Pi appliance that **detects drones, identifies them,
and logs where they (and their operators) are** — giving farmers and property
owners advance warning of surveillance overflights and an evidence-grade record
to hand to law enforcement.

It is **passive only**: it listens, it never transmits or interferes. See
[docs/LEGAL.md](docs/LEGAL.md).

## What it captures

| Layer | Catches | Yields | Hardware |
|-------|---------|--------|----------|
| **Remote ID — WiFi** (2.4/5.8 GHz) | Compliant drones (ASTM F3411) | Serial, model, **drone + operator GPS**, altitude, speed, heading | WiFi adapter (monitor mode) |
| **DJI DroneID** (proprietary) | DJI aircraft, incl. those not sending Remote ID | Serial, aircraft model, **drone + operator + home GPS**, full telemetry | same adapter |
| **Remote ID — Bluetooth** (BT4/BT5) | Compliant drones on the BT transport | Same telemetry, second transport | Bluetooth adapter |
| **RF presence** (sub-1.7 GHz) | Non-compliant / analog FPV | "Something is transmitting" on 433/900 MHz, 1.2 GHz | RTL-SDR |
| **Simulator** | — (demo/dev) | Synthetic traffic to run the whole UI with no radios | none |

**No GPL dependencies.** The entire capture stack — the 802.11/radiotap parser,
the RTL-SDR interface (`ctypes` → system `librtlsdr`), and the Bluetooth HCI
scanner — is first-party code using only the Python standard library. Only
permissive (MIT/BSD) packages are bundled. See [NOTICES.md](NOTICES.md).

> **Why the split?** GPS/identity live *inside* the Remote ID beacon, captured
> over WiFi/BT. An RTL-SDR can't see 2.4/5.8 GHz, so it serves as a presence
> backstop for silent drones. Both feed one pipeline.

## The interface

- **Live map** with dark basemap, Home Base + alert range rings.
- **Active contacts** panel — range/bearing from base, height, speed, heading,
  RSSI, and **operator location** when broadcast.
- **Proximity alerts** when a contact crosses the inner ring — on screen and
  pushed to the farmer's phone, with a tap-through to the operator's location
  ([setup](docs/ALERTS.md)).
- **Sighting log** — per-drone sessions (first/last seen, max altitude, hit
  count, whether an operator was logged).
- **Review mode** — scrub and replay any time window; watch tracks build with
  play / 4× / 16× / 60× speeds.

## Quick start (development — runs anywhere, simulator on)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate     |  Linux/macOS:  source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn app.main:app --reload --app-dir backend
```

Open <http://localhost:8000>. Synthetic drones appear immediately; open
**⚙ → Home Base** to set your location (click the map or type coordinates).

## Deploy to a Raspberry Pi 5 (Raspbian Trixie Lite 64-bit)

**One command** — installs and configures everything (quietly, in the
background) and leaves the appliance running. Auto-detects and enables an
attached RTL-SDR.

```bash
curl -fsSL https://raw.githubusercontent.com/DavidMGilbert/dronedingo/main/deploy/install.sh | sudo bash
```

Or from a clone: `sudo bash deploy/install.sh`. When it finishes, open the
dashboard URL it prints.

Enable the Remote ID radios you have, then `sudo systemctl restart dronedingo`:

```bash
# WiFi Remote ID (identity + GPS)
sudo bash /opt/dronedingo/deploy/monitor-mode.sh wlan1
# then set sources.wifi_remoteid.enabled: true in config/dronedingo.yaml

# Bluetooth Remote ID: set sources.bt_remoteid.enabled: true
# RTL-SDR presence: auto-enabled by the installer if a dongle is detected
```

## Self-test

```bash
/opt/dronedingo/.venv/bin/python -m unittest discover -s /opt/dronedingo/backend/tests -v
```

30 tests covering the Remote ID and DJI decoders, frame parsing, alert logic and
geo maths. See [docs/VALIDATION.md](docs/VALIDATION.md) for confirming the
decoders against real aircraft.

## Configuration

Everything lives in [`config/dronedingo.yaml`](config/dronedingo.yaml):

- **Re-badge the whole product** by changing `brand.product_name` / `accent`.
- Set default map centre, range rings, RTL-SDR bands & trigger threshold.
- `alerts.ntfy_topic` for free phone push; `alerts.webhook_url` for integrations.

## Architecture

```
 radios ─┐
 WiFi/BT │→ sources/  ─emit→  Manager ──→ SQLite (append-only, timestamped)
 RTL-SDR │  (threads)  (async queue)  └──→ WebSocket ──→ branded web UI
 sim ────┘                                              (map · telemetry · playback)
```

- `backend/app/sources/` — pluggable capture modules (one `Detection` schema).
- `backend/app/db.py` — evidence-grade storage + session log + retention.
- `frontend/` — self-contained Leaflet UI, re-brandable via config.

## Roadmap

- [x] First-party capture stack (no GPL deps)
- [x] Bluetooth Remote ID source
- [x] Single-command unattended installer
- [x] DJI proprietary DroneID decode (v1/v2, incl. operator position)
- [x] Phone push alerts (ntfy) + webhook
- [x] Offline vector basemap (appliance-served MapLibre)
- [x] Login-gated UI + admin panel (system/network/alerts/updates)
- [x] Light / dark themes; DroneDingo brand + Barlow type
- [x] In-UI updates (DroneDingo + OS)
- [ ] Multi-node fusion (triangulate non-GPS RF hits across sensors)
- [ ] Acoustic night-time detector
- [ ] Offline vector basemap bundle

## Licensing

Proprietary. Built on open-source components — see [NOTICES.md](NOTICES.md).
Legal posture in [docs/LEGAL.md](docs/LEGAL.md).
