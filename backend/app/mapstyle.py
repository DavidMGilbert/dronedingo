"""MapLibre style generation.

The basemap is generated from the brand palette rather than shipped as a static
file, so re-theming the product also re-themes the map. Three cases:

* **online raster** — the default OpenStreetMap tiles (needs internet)
* **offline raster** — raster MBTiles/PMTiles served by the appliance
* **offline vector** — vector tiles styled here, in DroneDingo colours

Vector styling supports the Protomaps basemap schema (what a Protomaps extract
produces) and the OpenMapTiles schema. Text labels require glyph files; they
are only emitted when a glyphs URL is configured, so a label-free basemap
renders cleanly with nothing extra to install.
"""
from __future__ import annotations


def _mix(hex_color: str, other: str, amount: float) -> str:
    """Blend two #rrggbb colours; amount 0 = first, 1 = second."""
    a = hex_color.lstrip("#")
    b = other.lstrip("#")
    out = []
    for i in (0, 2, 4):
        ca, cb = int(a[i:i + 2], 16), int(b[i:i + 2], 16)
        out.append(round(ca + (cb - ca) * amount))
    return "#%02x%02x%02x" % tuple(out)


def _palette(brand: dict) -> dict:
    """Derive map surface colours from the brand accent + a warm dark ground."""
    ground = "#141109"
    accent = brand.get("accent", "#E8963C")
    return {
        "earth": ground,
        "land": _mix(ground, accent, 0.06),
        "green": _mix(ground, "#4E7A3A", 0.35),
        "water": _mix(ground, "#2C6C8F", 0.55),
        "building": _mix(ground, accent, 0.13),
        "road_minor": _mix(ground, accent, 0.22),
        "road_major": _mix(ground, accent, 0.38),
        "road_hwy": _mix(ground, accent, 0.52),
        "boundary": _mix(ground, accent, 0.45),
        "label": _mix(ground, "#FFFFFF", 0.72),
        "label_halo": ground,
    }


def _raster_style(name: str, tiles_url: str, maxzoom: int,
                  attribution: str = "") -> dict:
    return {
        "version": 8,
        "name": name,
        "sources": {
            "basemap": {
                "type": "raster", "tiles": [tiles_url], "tileSize": 256,
                "maxzoom": maxzoom, "attribution": attribution,
            }
        },
        "layers": [
            {"id": "bg", "type": "background",
             "paint": {"background-color": "#141109"}},
            {"id": "basemap", "type": "raster", "source": "basemap",
             "paint": {
                 # Tone the imagery toward the product's warm dark palette.
                 "raster-brightness-max": 0.82,
                 "raster-saturation": -0.45,
                 "raster-contrast": 0.12,
             }},
        ],
    }


def _vector_layers_protomaps(p: dict) -> list[dict]:
    src = "basemap"
    L = lambda **kw: {"source": src, **kw}          # noqa: E731
    return [
        L(id="earth", type="fill", **{"source-layer": "earth"},
          paint={"fill-color": p["earth"]}),
        L(id="landuse", type="fill", **{"source-layer": "landuse"},
          paint={"fill-color": p["land"], "fill-opacity": 0.65}),
        L(id="natural", type="fill", **{"source-layer": "natural"},
          paint={"fill-color": p["green"], "fill-opacity": 0.5}),
        L(id="water", type="fill", **{"source-layer": "water"},
          paint={"fill-color": p["water"]}),
        L(id="buildings", type="fill", **{"source-layer": "buildings"},
          minzoom=13, paint={"fill-color": p["building"], "fill-opacity": 0.7}),
        L(id="roads-minor", type="line", **{"source-layer": "roads"},
          filter=["!=", ["get", "kind"], "highway"], minzoom=11,
          paint={"line-color": p["road_minor"],
                 "line-width": ["interpolate", ["linear"], ["zoom"],
                                11, 0.4, 16, 2.2]}),
        L(id="roads-major", type="line", **{"source-layer": "roads"},
          filter=["==", ["get", "kind"], "major_road"],
          paint={"line-color": p["road_major"],
                 "line-width": ["interpolate", ["linear"], ["zoom"],
                                8, 0.6, 16, 3.4]}),
        L(id="roads-highway", type="line", **{"source-layer": "roads"},
          filter=["==", ["get", "kind"], "highway"],
          paint={"line-color": p["road_hwy"],
                 "line-width": ["interpolate", ["linear"], ["zoom"],
                                6, 0.8, 16, 4.5]}),
        L(id="boundaries", type="line", **{"source-layer": "boundaries"},
          paint={"line-color": p["boundary"], "line-opacity": 0.5,
                 "line-dasharray": [3, 2], "line-width": 0.9}),
    ]


def _vector_layers_openmaptiles(p: dict) -> list[dict]:
    src = "basemap"
    L = lambda **kw: {"source": src, **kw}          # noqa: E731
    return [
        L(id="landcover", type="fill", **{"source-layer": "landcover"},
          paint={"fill-color": p["green"], "fill-opacity": 0.45}),
        L(id="landuse", type="fill", **{"source-layer": "landuse"},
          paint={"fill-color": p["land"], "fill-opacity": 0.6}),
        L(id="water", type="fill", **{"source-layer": "water"},
          paint={"fill-color": p["water"]}),
        L(id="buildings", type="fill", **{"source-layer": "building"},
          minzoom=13, paint={"fill-color": p["building"], "fill-opacity": 0.7}),
        L(id="roads-minor", type="line", **{"source-layer": "transportation"},
          minzoom=11, filter=["!in", "class", "motorway", "trunk", "primary"],
          paint={"line-color": p["road_minor"],
                 "line-width": ["interpolate", ["linear"], ["zoom"],
                                11, 0.4, 16, 2.2]}),
        L(id="roads-major", type="line", **{"source-layer": "transportation"},
          filter=["in", "class", "primary", "trunk"],
          paint={"line-color": p["road_major"],
                 "line-width": ["interpolate", ["linear"], ["zoom"],
                                8, 0.6, 16, 3.4]}),
        L(id="roads-highway", type="line", **{"source-layer": "transportation"},
          filter=["==", "class", "motorway"],
          paint={"line-color": p["road_hwy"],
                 "line-width": ["interpolate", ["linear"], ["zoom"],
                                6, 0.8, 16, 4.5]}),
        L(id="boundaries", type="line", **{"source-layer": "boundary"},
          paint={"line-color": p["boundary"], "line-opacity": 0.5,
                 "line-dasharray": [3, 2], "line-width": 0.9}),
    ]


def _label_layers(p: dict, schema: str) -> list[dict]:
    layer = "places" if schema == "protomaps" else "place"
    name_field = ["coalesce", ["get", "name:en"], ["get", "name"]]
    return [{
        "id": "place-labels", "source": "basemap", "source-layer": layer,
        "type": "symbol",
        "layout": {
            "text-field": name_field,
            "text-font": ["Noto Sans Regular"],
            "text-size": ["interpolate", ["linear"], ["zoom"], 8, 11, 14, 15],
        },
        "paint": {
            "text-color": p["label"],
            "text-halo-color": p["label_halo"],
            "text-halo-width": 1.4,
        },
    }]


def build_style(cfg: dict, store=None) -> dict:
    """Return a MapLibre style document for the current configuration."""
    brand = cfg.get("brand", {})
    mapcfg = cfg.get("map", {})
    basemap = mapcfg.get("basemap") or {}
    name = brand.get("product_name", "DroneDingo")

    # --- offline basemap served by the appliance --------------------------
    if store is not None:
        tiles_url = "{origin}/tiles/{z}/{x}/{y}"
        if not store.is_vector:
            return _raster_style(name, tiles_url, store.maxzoom)
        p = _palette(brand)
        schema = (basemap.get("schema") or "protomaps").lower()
        layers = [{"id": "bg", "type": "background",
                   "paint": {"background-color": p["earth"]}}]
        layers += (_vector_layers_protomaps(p) if schema == "protomaps"
                   else _vector_layers_openmaptiles(p))
        style = {
            "version": 8, "name": name,
            "sources": {"basemap": {
                "type": "vector", "tiles": [tiles_url],
                "minzoom": store.minzoom, "maxzoom": store.maxzoom,
            }},
            "layers": layers,
        }
        # Labels need glyph PBFs; only add them when glyphs are available.
        glyphs = basemap.get("glyphs_url")
        if glyphs:
            style["glyphs"] = glyphs
            style["layers"] += _label_layers(p, schema)
        return style

    # --- online raster fallback -------------------------------------------
    return _raster_style(
        name, mapcfg.get("tile_url", "https://tile.openstreetmap.org/{z}/{x}/{y}.png"),
        int(mapcfg.get("max_zoom", 19)),
        attribution="© OpenStreetMap contributors")
