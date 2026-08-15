# Offline / self-hosted maps

Farms often have poor connectivity. DroneDingo can install and serve a regional
map pack from the device itself. In the console open **Settings > Maps**, choose
a licensed `.pmtiles` or `.mbtiles` pack and select **Install map pack**. The
pack is validated, activated immediately and retained across software updates.

Map packs are stored in `data/basemaps/`. They are deliberately separate from
normal software releases: regional data can be several gigabytes and replacing
application code must never remove an owner's maps. The online OpenStreetMap
layer remains available as a reversible fallback.

## Option A — pre-rendered raster tiles (simplest)

1. Download an `.mbtiles` extract for your district/region (e.g. from a provider
   whose license permits rebranded/offline use).
2. Install it from **Settings > Maps**, or copy it into `data/basemaps/` and
   point the config at it:
   ```yaml
   map:
     basemap:
       path: "data/basemaps/your-region.mbtiles"
   ```

## Option B — bundled vector tiles (crisper, larger effort)

The MapLibre front end can use a `.pmtiles` vector extract served directly by
DroneDingo. Choose the matching Protomaps or OpenMapTiles schema while
installing it; the map is then styled from the active DroneDingo theme.

## Licensing note

If you distribute the appliance with a basemap, make sure the tile source's
license permits offline use and (for a proprietary look) the removal/relocation
of on-map attribution. OpenStreetMap's ODbL requires visible credit somewhere —
put it on an About/Legal screen. See `NOTICES.md`.
