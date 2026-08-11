/* ====================================================================
   DroneDingo — map layer (MapLibre GL)

   Wraps the renderer behind a small operation-based API so the rest of the
   app never touches MapLibre directly. Handles online raster, offline raster
   and offline vector basemaps identically — the style document decides.
   ==================================================================== */
window.DDMap = (() => {
  "use strict";

  const DRONE_SVG = '<svg class="glyph" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l2.4 4.8L20 8l-3.6 3.2L17 17l-5-2.6L7 17l.6-5.8L4 8l5.6-1.2z"/></svg>';
  const OP_SVG = '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><circle cx="12" cy="7" r="3.4"/><path d="M4.5 20c0-4.1 3.4-6.5 7.5-6.5s7.5 2.4 7.5 6.5z"/></svg>';

  let map = null;
  let ready = false;
  const pending = [];                 // ops queued until the style loads
  const drones = new Map();           // id -> maplibregl.Marker
  const operators = new Map();        // id -> maplibregl.Marker
  const tracks = new Map();           // id -> [[lon,lat], ...]
  let homeMarker = null;

  const themeColor = (name, fallback) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    || fallback;

  /** Run once the style is loaded, or immediately if it already is. */
  function whenReady(fn) { ready ? fn() : pending.push(fn); }

  function el(html, className) {
    const d = document.createElement("div");
    d.className = className || "";
    d.innerHTML = html;
    return d;
  }

  /* ---------------------------- sources ---------------------------- */
  function emptyFC() { return { type: "FeatureCollection", features: [] }; }

  function ensureOverlays() {
    if (map.getSource("dd-rings")) return;
    map.addSource("dd-rings", { type: "geojson", data: emptyFC() });
    map.addLayer({
      id: "dd-rings", type: "line", source: "dd-rings",
      paint: {
        "line-color": themeColor("--home", "#6C8CFF"),
        "line-opacity": 0.35, "line-width": 1, "line-dasharray": [4, 6],
      },
    });
    map.addSource("dd-tracks", { type: "geojson", data: emptyFC() });
    map.addLayer({
      id: "dd-tracks", type: "line", source: "dd-tracks",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": themeColor("--accent", "#E8963C"),
        "line-opacity": 0.75, "line-width": 2,
      },
    });
  }

  function pushTracks() {
    const src = map.getSource("dd-tracks");
    if (!src) return;
    const features = [];
    for (const [id, coords] of tracks) {
      if (coords.length > 1) {
        features.push({
          type: "Feature", properties: { id },
          geometry: { type: "LineString", coordinates: coords },
        });
      }
    }
    src.setData({ type: "FeatureCollection", features });
  }

  /** Approximate a circle of `radius` metres as a polygon ring. */
  function circleRing(lat, lon, radius, steps = 72) {
    const coords = [];
    const dLat = radius / 111320;
    const dLon = radius / (111320 * Math.cos(lat * Math.PI / 180));
    for (let i = 0; i <= steps; i++) {
      const t = (i / steps) * 2 * Math.PI;
      coords.push([lon + dLon * Math.cos(t), lat + dLat * Math.sin(t)]);
    }
    return coords;
  }

  /* ---------------------------- public API ---------------------------- */
  return {
    async init({ container, center, zoom, onClick }) {
      map = new maplibregl.Map({
        container,
        style: "/api/map/style",
        center: [center.lon, center.lat],
        zoom: zoom || 15,
        attributionControl: false,
        // Keep GPU/CPU use modest — this runs on a Pi-served browser session.
        fadeDuration: 0,
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }),
                     "top-left");
      map.on("click", (e) => onClick && onClick(e.lngLat.lat, e.lngLat.lng));
      await new Promise((res) => map.on("load", res));
      ensureOverlays();
      ready = true;
      pending.splice(0).forEach((fn) => fn());
      return map;
    },

    setHome(lat, lon, label, rings) {
      whenReady(() => {
        if (homeMarker) homeMarker.remove();
        homeMarker = new maplibregl.Marker({
          element: el("<div class='home-dot'></div>"),
        }).setLngLat([lon, lat])
          .setPopup(new maplibregl.Popup({ offset: 14, closeButton: false })
            .setText(label || "Home Base"))
          .addTo(map);
        const features = (rings || []).map((r) => ({
          type: "Feature", properties: { r },
          geometry: { type: "Polygon", coordinates: [circleRing(lat, lon, r)] },
        }));
        map.getSource("dd-rings").setData(
          { type: "FeatureCollection", features });
      });
    },

    upsertDrone(id, lat, lon, heading, threat, label, onSelect) {
      whenReady(() => {
        let m = drones.get(id);
        if (!m) {
          const node = el(DRONE_SVG, "drone-marker");
          node.addEventListener("click", (ev) => {
            ev.stopPropagation();
            onSelect && onSelect(id);
          });
          m = new maplibregl.Marker({ element: node })
            .setLngLat([lon, lat]).addTo(map);
          drones.set(id, m);
        } else {
          m.setLngLat([lon, lat]);
        }
        const node = m.getElement();
        node.classList.toggle("threat", !!threat);
        node.title = label || "";
        const glyph = node.querySelector(".glyph");
        if (glyph) glyph.style.transform = `rotate(${heading || 0}deg)`;
      });
    },

    upsertOperator(id, lat, lon) {
      whenReady(() => {
        let m = operators.get(id);
        if (!m) {
          const node = el(OP_SVG, "op-marker");
          node.title = "Operator";
          m = new maplibregl.Marker({ element: node })
            .setLngLat([lon, lat]).addTo(map);
          operators.set(id, m);
        } else {
          m.setLngLat([lon, lat]);
        }
      });
    },

    setTrack(id, positions) {
      whenReady(() => {
        tracks.set(id, positions.map(([lat, lon]) => [lon, lat]));
        pushTracks();
      });
    },

    removeContact(id) {
      whenReady(() => {
        const d = drones.get(id); if (d) { d.remove(); drones.delete(id); }
        const o = operators.get(id); if (o) { o.remove(); operators.delete(id); }
        if (tracks.delete(id)) pushTracks();
      });
    },

    /** Remove the aircraft/operator markers but keep the flown track drawn.
     *  Used during playback when a contact is not airborne at the playhead. */
    hideMarkers(id) {
      whenReady(() => {
        const d = drones.get(id); if (d) { d.remove(); drones.delete(id); }
        const o = operators.get(id); if (o) { o.remove(); operators.delete(id); }
      });
    },

    clearContacts() {
      whenReady(() => {
        drones.forEach((m) => m.remove()); drones.clear();
        operators.forEach((m) => m.remove()); operators.clear();
        tracks.clear(); pushTracks();
      });
    },

    panTo(lat, lon) {
      whenReady(() => map.easeTo({ center: [lon, lat], duration: 500 }));
    },

    /** Re-apply the style (used after a theme or basemap change). */
    reloadStyle() {
      whenReady(() => {
        map.setStyle("/api/map/style");
        map.once("styledata", () => { ensureOverlays(); pushTracks(); });
      });
    },
  };
})();
