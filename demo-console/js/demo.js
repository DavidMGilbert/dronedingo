/* ====================================================================
   DroneDingo — static, read-only console demo.
   Locates the visitor, drops a nearby "property", and simulates drones with
   organic wandering flight. No backend, no auth. Client-side only.
   ==================================================================== */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const rad = (d) => d * Math.PI / 180, deg = (r) => r * 180 / Math.PI;
  const R = 6371000;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const rnd = (a, b) => a + Math.random() * (b - a);

  const ICON_DRONE = '<svg viewBox="0 0 24 24" fill="currentColor">'
    + '<path d="M12 2.6l1.6 3H10.4z"/>'
    + '<line x1="7" y1="7" x2="17" y2="17" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>'
    + '<line x1="17" y1="7" x2="7" y2="17" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>'
    + '<circle cx="5.6" cy="5.6" r="2.7"/><circle cx="18.4" cy="5.6" r="2.7"/>'
    + '<circle cx="5.6" cy="18.4" r="2.7"/><circle cx="18.4" cy="18.4" r="2.7"/>'
    + '<rect x="9.3" y="9.3" width="5.4" height="5.4" rx="1.5"/></svg>';
  const ICON_OP = '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="8" r="3.4"/>'
    + '<path d="M5 20c0-4 3.2-6.4 7-6.4s7 2.4 7 6.4z"/></svg>';

  const MODELS = ["DJI Mavic 3", "DJI Air 3", "Autel EVO II", "DJI Mini 4 Pro", "DJI FPV"];
  const RINGS = [250, 500, 1000];

  /* ---- geo helpers ---- */
  function offsetM(lat, lon, north, east) {
    const dLat = north / R, dLon = east / (R * Math.cos(rad(lat)));
    return [lat + deg(dLat), lon + deg(dLon)];
  }
  function haversine(a, b, c, d) {
    const dphi = rad(c - a), dl = rad(d - b);
    const s = Math.sin(dphi / 2) ** 2 + Math.cos(rad(a)) * Math.cos(rad(c)) * Math.sin(dl / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(s));
  }
  function bearing(a, b, c, d) {
    const y = Math.sin(rad(d - b)) * Math.cos(rad(c));
    const x = Math.cos(rad(a)) * Math.sin(rad(c)) - Math.sin(rad(a)) * Math.cos(rad(c)) * Math.cos(rad(d - b));
    return (deg(Math.atan2(y, x)) + 360) % 360;
  }
  function blendAngle(a, t, k) {
    let diff = ((t - a + 540) % 360) - 180;
    return a + diff * k;
  }
  const compass = (b) => ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"][Math.round(b / 22.5) % 16];
  const fmtDist = (m) => m >= 1000 ? (m / 1000).toFixed(2) + " km" : Math.round(m) + " m";

  /* ---- wandering drone ---- */
  function makeDrone(id, model, home, maxR, baseSpeed) {
    const a = rnd(0, 2 * Math.PI), r = rnd(0.2, 0.8) * maxR;
    const [lat, lon] = offsetM(home.lat, home.lon, r * Math.cos(a), r * Math.sin(a));
    const oa = rnd(0, 2 * Math.PI), orr = rnd(0.4, 1.1) * maxR;
    const [oplat, oplon] = offsetM(home.lat, home.lon, orr * Math.cos(oa), orr * Math.sin(oa));
    return {
      id, model, home, maxR, lat, lon, oplat, oplon,
      heading: rnd(0, 360), speed: baseSpeed, curSpeed: baseSpeed, targetSpeed: baseSpeed,
      alt: rnd(35, 95), targetAlt: rnd(35, 95), vspeed: 0,
      rssiBase: rnd(-52, -38), positions: [], seen: Date.now(),
      step(dt) {
        this.heading += rnd(-1, 1) * 28 * dt;                 // gentle wander
        if (Math.random() < 0.02) this.heading += rnd(-1, 1) * 110;   // occasional turn
        const dHome = haversine(this.lat, this.lon, this.home.lat, this.home.lon);
        if (dHome > this.maxR) {                              // steer back over the property
          const toHome = bearing(this.lat, this.lon, this.home.lat, this.home.lon);
          this.heading = blendAngle(this.heading, toHome, clamp((dHome - this.maxR) / this.maxR, 0, 1) * 0.5 + 0.15);
        }
        this.heading = ((this.heading % 360) + 360) % 360;
        if (Math.random() < 0.012) { this.targetSpeed = this.speed * rnd(0.4, 1.4); this.targetAlt = rnd(25, 110); }
        this.curSpeed += (this.targetSpeed - this.curSpeed) * 0.06;
        this.vspeed = clamp((this.targetAlt - this.alt) * 0.2, -3, 3);
        this.alt += this.vspeed * dt;
        const dist = this.curSpeed * dt;
        [this.lat, this.lon] = offsetM(this.lat, this.lon,
          dist * Math.cos(rad(this.heading)), dist * Math.sin(rad(this.heading)));
        this.positions.push([this.lat, this.lon]);
        if (this.positions.length > 240) this.positions.shift();
      },
    };
  }

  /* ---- map ---- */
  const style = {
    version: 8,
    sources: { base: { type: "raster", tileSize: 256,
      tiles: ["https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
              "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
              "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"],
      attribution: '© OpenStreetMap contributors © CARTO' } },
    layers: [{ id: "bg", type: "background", paint: { "background-color": "#0b1416" } },
             { id: "base", type: "raster", source: "base" }],
  };

  let map, drones = [], home, markers = { drones: new Map(), ops: new Map(), home: null };
  const themeColor = (n, f) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || f;
  const el = (html, cls) => { const d = document.createElement("div"); d.className = cls || ""; d.innerHTML = html; return d; };

  function circle(lat, lon, radius, steps = 72) {
    const c = [];
    for (let i = 0; i <= steps; i++) {
      const t = i / steps * 2 * Math.PI;
      c.push(offsetM(lat, lon, radius * Math.sin(t), radius * Math.cos(t)).reverse());
    }
    return c;
  }

  function start(center, located) {
    // Put the "property" a little away from the exact visitor point.
    const [hlat, hlon] = offsetM(center.lat, center.lon, rnd(-350, 350), rnd(-350, 350));
    home = { lat: hlat, lon: hlon };

    map = new maplibregl.Map({ container: "map", style, center: [hlon, hlat], zoom: 15.2, attributionControl: true });
    // A map created before its container has a size renders blank; nudge it once
    // the layout settles, and whenever the window changes.
    map.on("error", (e) => console.warn("[demo] map:", e && e.error && e.error.message));
    window.addEventListener("resize", () => map.resize());
    [120, 500, 1500].forEach((ms) => setTimeout(() => map && map.resize(), ms));
    map.on("load", () => {
      map.resize();
      map.addSource("rings", { type: "geojson", data: {
        type: "FeatureCollection", features: RINGS.map((r) => ({
          type: "Feature", geometry: { type: "Polygon", coordinates: [circle(hlat, hlon, r)] } })) } });
      map.addLayer({ id: "rings", type: "line", source: "rings",
        paint: { "line-color": themeColor("--home", "#4E6BE6"), "line-opacity": 0.35, "line-width": 1, "line-dasharray": [4, 6] } });
      map.addSource("tracks", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({ id: "tracks", type: "line", source: "tracks",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": themeColor("--orange", "#ed9800"), "line-opacity": 0.7, "line-width": 2 } });

      markers.home = new maplibregl.Marker({ element: el("<div class='home-dot'></div>") }).setLngLat([hlon, hlat]).addTo(map);

      // spawn a few wandering drones
      const n = 2 + Math.floor(Math.random() * 2);
      const used = new Set();
      for (let i = 0; i < n; i++) {
        let m; do { m = MODELS[Math.floor(Math.random() * MODELS.length)]; } while (used.has(m) && used.size < MODELS.length);
        used.add(m);
        const serial = (m.startsWith("DJI") ? "1581F5" : "SIM-AUT") + Math.random().toString(36).slice(2, 8).toUpperCase();
        drones.push(makeDrone(serial, m, home, rnd(450, 750), rnd(4, 12)));
      }
      geoNote(located);
      setInterval(tick, 1000);
      tick();
    });
  }

  function tick() {
    for (const d of drones) d.step(1.0);
    // tracks
    map.getSource("tracks").setData({ type: "FeatureCollection", features: drones.map((d) => ({
      type: "Feature", geometry: { type: "LineString", coordinates: d.positions.map(([la, lo]) => [lo, la]) } })) });

    const inner = RINGS[0];
    let threat = null;
    const rows = drones.map((d) => {
      const range = haversine(home.lat, home.lon, d.lat, d.lon);
      const brg = bearing(home.lat, home.lon, d.lat, d.lon);
      const opRange = haversine(home.lat, home.lon, d.oplat, d.oplon);
      const rssi = Math.round(d.rssiBase - 0.02 * range + rnd(-2, 2));
      const isThreat = range <= inner;
      if (isThreat && (!threat || range < threat.range)) threat = { d, range, brg };
      // markers
      let dm = markers.drones.get(d.id);
      if (!dm) {
        const node = el(ICON_DRONE, "drone-marker"); node.firstChild.classList.add("glyph");
        dm = new maplibregl.Marker({ element: node }).setLngLat([d.lon, d.lat]).addTo(map);
        markers.drones.set(d.id, dm);
      } else dm.setLngLat([d.lon, d.lat]);
      const node = dm.getElement();
      node.classList.toggle("threat", isThreat);
      const g = node.querySelector(".glyph"); if (g) g.style.transform = `rotate(${d.heading}deg)`;
      let om = markers.ops.get(d.id);
      if (!om) { om = new maplibregl.Marker({ element: el(ICON_OP, "op-marker") }).setLngLat([d.oplon, d.oplat]).addTo(map); markers.ops.set(d.id, om); }
      return { d, range, brg, opRange, rssi };
    }).sort((a, b) => a.range - b.range);

    // contact cards
    $("contact-count").textContent = drones.length;
    $("contacts-empty").style.display = drones.length ? "none" : "";
    $("contact-list").innerHTML = rows.map(({ d, range, brg, opRange, rssi }) => `
      <div class="contact-card">
        <span class="contact-head"><span class="drone-icon">${ICON_DRONE}</span>
          <span class="contact-name"><strong>${d.model}</strong><small>RID/WiFi (sim) · ${d.id}</small></span>
          <span class="contact-distance">${fmtDist(range)}</span></span>
        <span class="telemetry">
          <span><small>Range</small>${compass(brg)}</span>
          <span><small>Height</small>${Math.round(d.alt)} m</span>
          <span><small>Speed</small>${d.curSpeed.toFixed(1)} m/s</span>
          <span><small>Heading</small>${Math.round(d.heading)}°</span>
          <span><small>V-Speed</small>${d.vspeed.toFixed(1)} m/s</span>
          <span><small>Signal</small>${rssi} dBm</span>
        </span>
        <span class="operator-line"><span class="operator-icon">${ICON_OP}</span>Operator estimated ${fmtDist(opRange)} from base</span>
      </div>`).join("");

    // alert strip
    const strip = $("alert-strip");
    if (threat) {
      $("alert-text").innerHTML = `<strong>${threat.d.model}</strong> within ${fmtDist(threat.range)} of the property — bearing ${compass(threat.brg)}`;
      strip.hidden = false;
    } else strip.hidden = true;
  }

  function geoNote(located) {
    const n = $("geo-note");
    n.innerHTML = located
      ? "Showing <b>simulated</b> drone detections near your location."
      : "Location unavailable — showing a <b>sample</b> property. This is a simulation.";
    setTimeout(() => { n.style.transition = "opacity .6s"; n.style.opacity = "0"; setTimeout(() => n.remove(), 700); }, 5000);
  }

  function tickClock() {
    const d = new Date();
    $("clock").textContent = d.toLocaleTimeString("en-AU", { hour12: false });
    $("current-date").textContent = d.toLocaleDateString("en-AU", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
  }
  tickClock(); setInterval(tickClock, 1000);

  // A few plausible rural fallbacks if geolocation is blocked.
  const FALLBACKS = [
    { lat: -32.0474, lon: 151.8311 },  // Faulkland NSW
    { lat: -34.5, lon: 148.35 },       // Riverina NSW
    { lat: -37.75, lon: 143.35 },      // western VIC
    { lat: -27.55, lon: 151.95 },      // Darling Downs QLD
    { lat: -31.95, lon: 116.0 },       // WA wheatbelt
  ];
  const fallback = () => FALLBACKS[Math.floor(Math.random() * FALLBACKS.length)];

  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      (pos) => start({ lat: pos.coords.latitude, lon: pos.coords.longitude }, true),
      () => start(fallback(), false),
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 600000 });
  } else {
    start(fallback(), false);
  }
})();
