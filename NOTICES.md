# Third-party notices

DroneDingo is a proprietary product. Its **capture stack is entirely first-party**
— the WiFi 802.11/radiotap parser, the RTL-SDR interface, and the Bluetooth HCI
scanner are our own code using only the Python standard library. There are **no
GPL/copyleft dependencies** bundled with the product.

The remaining runtime dependencies are all permissive (MIT / BSD) and may be
redistributed inside the appliance. This file preserves their attribution while
keeping the product presentation unbranded with respect to them.

| Component | Purpose | License |
|-----------|---------|---------|
| FastAPI / Starlette | Web framework & WebSocket | MIT |
| Uvicorn | ASGI server | BSD-3-Clause |
| PyYAML | Config parsing | MIT |
| aiosqlite | Async SQLite | MIT |
| itsdangerous | Signed session cookies | BSD-3-Clause |
| cryptography | Ed25519 release-signature verification | Apache-2.0 / BSD |
| MapLibre GL JS (vendored, `frontend/vendor/maplibre`) | Map rendering | BSD-3-Clause |
| Barlow / Barlow Condensed (vendored, `frontend/vendor/fonts`) | Typography | SIL Open Font License 1.1 |
| OpenStreetMap tiles (optional/online) | Basemap imagery | ODbL (© OpenStreetMap contributors) |

## System libraries (not redistributed by us)

- **librtlsdr** (`librtlsdr0`, GPL-2.0) is installed from the operating system's
  own package repository by the installer (`apt`). We load it dynamically via a
  `ctypes` binding, the same way any application links a system library. We do
  **not** copy, modify, or redistribute it, so its copyleft terms are not
  triggered by DroneDingo's distribution. If you build a bundled OS *image* that
  includes it, ship librtlsdr's license text with that image.

## Basemap attribution

If you ship the online OpenStreetMap basemap, ODbL requires visible
"© OpenStreetMap contributors" credit. The on-map attribution control is hidden
for the appliance look — place the credit on an About/Legal screen, or self-host
tiles you are licensed to rebrand (see `docs/OFFLINE_MAPS.md`).
