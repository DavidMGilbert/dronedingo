# Third-party notices

SkyWarden is a proprietary product built on open-source components. The UI is
deliberately unbranded with respect to these dependencies, but their licenses
require that attribution be retained somewhere in the distribution — this file
satisfies that while keeping the product presentation clean.

| Component | Purpose | License |
|-----------|---------|---------|
| FastAPI / Starlette | Web framework & WebSocket | MIT |
| Uvicorn | ASGI server | BSD-3-Clause |
| PyYAML | Config parsing | MIT |
| aiosqlite | Async SQLite | MIT |
| Leaflet | Map rendering | BSD-2-Clause |
| OpenStreetMap tiles | Basemap imagery | ODbL (© OpenStreetMap contributors) |
| scapy | WiFi frame capture (optional) | GPL-2.0 |
| pyrtlsdr / librtlsdr | RTL-SDR interface (optional) | GPL-3.0 / GPL-2.0 |
| bleak | Bluetooth capture (optional) | MIT |

**Basemap attribution:** if you ship the online OpenStreetMap basemap, ODbL
requires visible "© OpenStreetMap contributors" credit. The attribution control
is hidden in the appliance chrome; place the credit in your About/Legal screen,
or self-host tiles you are licensed to rebrand (see `docs/OFFLINE_MAPS.md`).

**GPL components (scapy, pyrtlsdr) are optional capture plugins** invoked as
separate processes/imports at runtime and are not modified. If you distribute a
node with them installed, include their license texts alongside this file.
