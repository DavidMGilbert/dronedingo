# Offline / self-hosted maps

Farms often have poor connectivity. SkyWarden reads its basemap URL from
`config/skywarden.yaml` (`map.tile_url`), so switching to offline tiles needs
**no code changes**.

## Option A — pre-rendered raster tiles (simplest)

1. Download an `.mbtiles` extract for your county/region (e.g. from a provider
   whose license permits rebranded/offline use).
2. Serve it locally on the Pi with a lightweight tile server, e.g.:
   ```bash
   pip install mbutil
   # or run a small tileserver container / go-mbtiles binary
   ```
3. Point the config at it:
   ```yaml
   map:
     tile_url: "http://localhost:8080/{z}/{x}/{y}.png"
   ```

## Option B — bundled vector tiles (crisper, larger effort)

Use a MapLibre-based front end with a self-hosted style + a `.pmtiles` file
served from the appliance. This is a later upgrade path; the current UI uses
Leaflet raster tiles for simplicity and low resource use on the Pi.

## Licensing note

If you distribute the appliance with a basemap, make sure the tile source's
license permits offline use and (for a proprietary look) the removal/relocation
of on-map attribution. OpenStreetMap's ODbL requires visible credit somewhere —
put it on an About/Legal screen. See `NOTICES.md`.
