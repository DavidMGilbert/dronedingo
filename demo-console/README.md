# demo.dronedingo.com.au — static console demo

A self-contained, **no-auth, read-only** demo of the DroneDingo console. It
locates the visitor, drops a nearby "property", and simulates drones with
**organic wandering flight** (no repeating paths). Entirely client-side — no
backend, no database, no keys.

## Deploy

Point the `demo.dronedingo.com.au` docroot at this folder (or upload its
contents to the web root). That's it — it's plain static files.

- **HTTPS is recommended.** Browser geolocation only works on a secure origin,
  so on http/localhost the demo falls back to a random sample rural property.
  On https it centres on the visitor.
- **Internet needed for the basemap** — it uses CARTO's free dark raster tiles
  (`© OpenStreetMap contributors © CARTO`, attributed on the map). No API key.

## What it does

- Asks for location once; on allow, centres a demo property near the visitor.
- Spawns 2–3 drones, each with an operator nearby, and flies them with a
  bounded random-walk (gentle heading drift, occasional turns, speed/altitude
  changes, and a steer-back so they loiter over the property). Every run and
  every second is different.
- Shows the real console UI: liquid-glass panels, quad drone / operator / home
  markers, live tracks, VFD telemetry, and the amber proximity alert when a
  drone crosses the inner ring.

## Notes

- No settings, no login, nothing writable — safe to expose publicly.
- To change the look, it reuses the same `css/` theme as the appliance; swap the
  logo at `vendor/brand/mark-dark.png`.
- Tiles: to self-host or change the basemap, edit the `style.sources.base.tiles`
  URLs in `js/demo.js`.
