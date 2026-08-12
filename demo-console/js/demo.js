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
  const UFO_SVG = '<svg viewBox="0 0 24 24" fill="currentColor">'
    + '<ellipse cx="12" cy="12" rx="9" ry="3.4"/>'                          // saucer
    + '<path d="M8.2 10.7a3.8 2.9 0 0 1 7.6 0z"/>'                          // dome
    + '<circle cx="6.6" cy="16.8" r=".9"/><circle cx="12" cy="18.3" r=".9"/><circle cx="17.4" cy="16.8" r=".9"/></svg>'; // beam

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
  // Survey-style waypoints so drones look like they're scanning a property.
  function buildWaypoints(pattern, home, R) {
    const pts = [], push = (n, e) => pts.push(offsetM(home.lat, home.lon, n, e));
    if (pattern === "orbit" || pattern === "hover") {
      const n = pattern === "hover" ? 5 : 12;
      for (let i = 0; i < n; i++) { const a = i / n * 2 * Math.PI, rr = R * (pattern === "hover" ? rnd(0.25, 1) : rnd(0.85, 1.05)); push(rr * Math.cos(a), rr * Math.sin(a)); }
    } else if (pattern === "perimeter") {
      for (const [n, e] of [[R, R], [R, -R], [-R, -R], [-R, R]]) push(n * rnd(0.85, 1.05), e * rnd(0.85, 1.05));
    } else { // lawnmower grid
      const rows = 4; let dir = 1;
      for (let i = 0; i <= rows; i++) { const n = -R + 2 * R * i / rows; push(n, dir * R); push(n, -dir * R); dir *= -1; }
    }
    return pts;
  }

  function makeDrone(id, model, home, maxR, baseSpeed, unidentified) {
    const pattern = unidentified ? "hover" : ["perimeter", "grid", "orbit"][Math.floor(Math.random() * 3)];
    const wps = buildWaypoints(pattern, home, maxR);
    const [lat, lon] = wps[0];
    const oa = rnd(0, 2 * Math.PI), orr = rnd(0.4, 1.1) * maxR;
    const [oplat, oplon] = offsetM(home.lat, home.lon, orr * Math.cos(oa), orr * Math.sin(oa));
    return {
      id, model, home, maxR, lat, lon, oplat, oplon, pattern, wps, wpi: 1, hover: 0,
      unidentified: !!unidentified, hasOp: !unidentified,
      heading: rnd(0, 360), speed: baseSpeed, curSpeed: baseSpeed,
      alt: rnd(35, 95), targetAlt: rnd(35, 95), vspeed: 0,
      rssiBase: rnd(-52, -38), positions: [],
      step(dt) {
        const [tlat, tlon] = this.wps[this.wpi];
        const dist = haversine(this.lat, this.lon, tlat, tlon);
        if (this.hover > 0) {                                  // pause on station = "scanning"
          this.hover -= dt;
          this.curSpeed += (0 - this.curSpeed) * 0.15;
          this.heading += rnd(-1, 1) * 18 * dt;                // slow rotate while scanning
        } else if (dist < 18) {                                // reached a survey point
          this.wpi = (this.wpi + 1) % this.wps.length;
          if (this.wpi === 0) this.wps = buildWaypoints(this.pattern, this.home, this.maxR); // re-jitter each lap
          if (Math.random() < 0.45) this.hover = rnd(1.5, 4);  // occasionally hold & scan
        } else {                                               // fly toward the point (steer + jitter)
          this.heading = blendAngle(this.heading, bearing(this.lat, this.lon, tlat, tlon), 0.16) + rnd(-1, 1) * 6;
          this.curSpeed += (this.speed - this.curSpeed) * 0.06;
        }
        this.heading = ((this.heading % 360) + 360) % 360;
        if (Math.random() < 0.01) this.targetAlt = rnd(30, 105);
        this.vspeed = clamp((this.targetAlt - this.alt) * 0.2, -3, 3);
        this.alt += this.vspeed * dt;
        const span = Math.max(0, this.curSpeed) * dt;
        [this.lat, this.lon] = offsetM(this.lat, this.lon, span * Math.cos(rad(this.heading)), span * Math.sin(rad(this.heading)));
        this.positions.push([this.lat, this.lon]);
        if (this.positions.length > 240) this.positions.shift();
      },
    };
  }

  /* ---- map ---- */
  // Raster paint + background per theme, mirroring the appliance's mapstyle.py
  // so CARTO's OSM tiles take on the DroneDingo warm/desaturated look.
  const RASTER_TINT = {
    dark:  { "raster-brightness-max": 0.82, "raster-saturation": -0.45, "raster-contrast": 0.12 },
    light: { "raster-saturation": -0.15, "raster-contrast": 0.04 },
  };
  const THEME_BG = { dark: "#141109", light: "#F1ECE2" };

  const style = {
    version: 8,
    sources: { base: { type: "raster", tileSize: 256,
      tiles: ["https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
              "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
              "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"],
      attribution: '© OpenStreetMap contributors © CARTO' } },
    layers: [{ id: "bg", type: "background", paint: { "background-color": "#141109" } },
             // Same warm tint the appliance applies over the raster basemap
             // (mapstyle.py) so the demo and the real console look identical.
             { id: "base", type: "raster", source: "base", paint: RASTER_TINT.dark }],
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
      // One UNIDENTIFIED contact — no Remote ID, no telemetry. The differentiator.
      // Kept near home (we can't know its real position) and loitering slowly.
      drones.push(makeDrone("RF-UNRESOLVED-" + Math.random().toString(36).slice(2, 6).toUpperCase(),
        "Unidentified drone", home, rnd(90, 170), rnd(3, 6), true));
      geoNote(located);
      setInterval(tick, 1000);
      tick();
    });
  }

  function cardHTML({ d, range, brg, opRange, rssi }) {
    if (d.unidentified) {
      return `<div class="contact-card unidentified">
        <span class="contact-head"><span class="drone-icon" style="color:var(--danger)">${UFO_SVG}</span>
          <span class="contact-name"><strong>Unidentified drone<span class="unid-tag">No ID</span></strong><small>RF signature · identity not broadcast</small></span>
          <span class="contact-distance" style="color:var(--danger)">~${fmtDist(range)}</span></span>
        <span class="unid-note"><b>Not transmitting Remote ID.</b> Detected by its control-link signature — no serial, operator or precise telemetry. You still know a drone is out there.</span>
      </div>`;
    }
    return `<div class="contact-card">
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
    </div>`;
  }

  function tick() {
    for (const d of drones) d.step(1.0);
    // tracks — identified only (an unidentified contact's position is uncertain)
    map.getSource("tracks").setData({ type: "FeatureCollection", features: drones.filter((d) => !d.unidentified).map((d) => ({
      type: "Feature", geometry: { type: "LineString", coordinates: d.positions.map(([la, lo]) => [lo, la]) } })) });

    const inner = RINGS[0];
    let threat = null, unid = 0;
    const rows = drones.map((d) => {
      const range = haversine(home.lat, home.lon, d.lat, d.lon);
      const brg = bearing(home.lat, home.lon, d.lat, d.lon);
      const opRange = d.hasOp ? haversine(home.lat, home.lon, d.oplat, d.oplon) : null;
      const rssi = Math.round(d.rssiBase - 0.02 * range + rnd(-2, 2));
      const isThreat = range <= inner;
      if (isThreat && (!threat || range < threat.range)) threat = { d, range, brg };
      if (d.unidentified) unid++;

      let dm = markers.drones.get(d.id);
      if (d.unidentified) {
        if (!dm) { dm = new maplibregl.Marker({ element: el(UFO_SVG, "unid-marker") }).setLngLat([d.lon, d.lat]).addTo(map); markers.drones.set(d.id, dm); }
        else dm.setLngLat([d.lon, d.lat]);
      } else {
        if (!dm) {
          const node = el(ICON_DRONE, "drone-marker"); node.firstChild.classList.add("glyph");
          dm = new maplibregl.Marker({ element: node }).setLngLat([d.lon, d.lat]).addTo(map);
          markers.drones.set(d.id, dm);
        } else dm.setLngLat([d.lon, d.lat]);
        const node = dm.getElement();
        node.classList.toggle("threat", isThreat);
        const g = node.querySelector(".glyph"); if (g) g.style.transform = `rotate(${d.heading}deg)`;
      }
      if (d.hasOp && !markers.ops.get(d.id)) {
        markers.ops.set(d.id, new maplibregl.Marker({ element: el(ICON_OP, "op-marker") }).setLngLat([d.oplon, d.oplat]).addTo(map));
      }
      return { d, range, brg, opRange, rssi };
    }).sort((a, b) => (b.d.unidentified - a.d.unidentified) || (a.range - b.range)); // unidentified pinned to top

    $("contact-count").textContent = drones.length;
    $("contacts-empty").style.display = drones.length ? "none" : "";
    $("contact-list").innerHTML = rows.map(cardHTML).join("");

    const chip = $("rf-chip");
    if (unid) { $("rf-chip-text").textContent = `${unid} unidentified drone${unid > 1 ? "s" : ""} — no Remote ID`; chip.hidden = false; }
    else chip.hidden = true;

    const strip = $("alert-strip");
    if (threat) {
      $("alert-text").innerHTML = `<strong>${threat.d.unidentified ? "Unidentified drone" : threat.d.model}</strong> within ${fmtDist(threat.range)} of the property — bearing ${compass(threat.brg)}`;
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

  /* ---- console chrome: theme, sighting log, settings, CTA ---- */
  function swapTiles(theme) {
    if (!map || !map.getSource) return;
    const v = theme === "light" ? "light_all" : "dark_all";
    const src = map.getSource("base");
    if (src && src.setTiles) src.setTiles(["a", "b", "c"].map((s) => `https://${s}.basemaps.cartocdn.com/${v}/{z}/{x}/{y}.png`));
    map.setPaintProperty("bg", "background-color", THEME_BG[theme] || THEME_BG.dark);
    // Re-apply the appliance's per-theme tint over the raster layer.
    const tint = RASTER_TINT[theme] || RASTER_TINT.dark;
    for (const prop of ["raster-brightness-max", "raster-saturation", "raster-contrast"])
      map.setPaintProperty("base", prop, tint[prop] === undefined ? (prop === "raster-brightness-max" ? 1 : 0) : tint[prop]);
  }
  function toggleTheme() {
    const next = (document.documentElement.getAttribute("data-theme") || "dark") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    $("btn-theme").textContent = next === "dark" ? "☀" : "☾";
    swapTiles(next);
  }

  const layer = () => $("modal-layer");
  function openModal(id) { layer().hidden = false; document.querySelectorAll("#modal-layer .modal").forEach((m) => m.hidden = m.id !== id); }
  function closeModals() { layer().hidden = true; document.querySelectorAll("#modal-layer .modal").forEach((m) => m.hidden = true); }

  const SIGHTINGS = [
    { name: "DJI Mavic 3", serial: "1581F5FKD2440100", first: "Today 19:38", dur: "01:03:52", range: "498 m", hits: "3,593" },
    { name: "Autel EVO II", serial: "SIM-AUTEL-EVO-0079", first: "Today 18:12", dur: "00:41:09", range: "210 m", hits: "2,140" },
    { name: "Unidentified drone", serial: "RF-UNRESOLVED-0031", first: "Today 14:05", dur: "00:06:44", range: "~180 m", hits: "392", unid: true },
    { name: "DJI Mini 4 Pro", serial: "SIM-DJI-M4P-1042", first: "Yesterday 16:21", dur: "00:08:14", range: "1.2 km", hits: "492" },
    { name: "Unidentified drone", serial: "RF-UNRESOLVED-0027", first: "8 Aug 18:03", dur: "00:03:18", range: "~934 m", hits: "198", unid: true },
    { name: "DJI Air 3", serial: "SIM-DJI-AIR3-5521", first: "6 Aug 14:12", dur: "00:11:09", range: "742 m", hits: "669" },
  ];
  function renderSightings() {
    $("sighting-rows").innerHTML = SIGHTINGS.map((s) =>
      `<tr${s.unid ? ' style="color:var(--danger)"' : ""}>`
      + `<td><strong>${s.unid ? "🛸 " : ""}${s.name}</strong><br><small>${s.serial}${s.unid ? " · no Remote ID" : ""}</small></td>`
      + `<td>${s.first}</td><td>${s.dur}</td><td>${s.range}</td><td>${s.hits}</td></tr>`).join("");
  }

  const SETTINGS = {
    Location: "Set the receiver location — range and bearing to every contact are measured from here.",
    Alerts: "Register phones for end-to-end encrypted push alerts, straight from the appliance. No third-party app, no Apple/Google account.",
    System: "Live appliance health — CPU, memory, temperature and Pi throttle status at a glance.",
    Network: "Configure Wi-Fi and ethernet directly from the dashboard.",
    Updates: "One-click DroneDingo software and firmware updates.",
    Account: "Manage the admin login and registered devices.",
    About: "Version, build and node information.",
  };
  function paneHTML(k) {
    return `<h3>${k}</h3><p>${SETTINGS[k]}</p><p style="margin-top:14px">`
      + `<a href="https://dronedingo.com.au/the-system" target="_blank" rel="noopener" style="color:var(--orange);font-weight:600">See the full system →</a></p>`;
  }
  function buildSettings() {
    const nav = $("settings-nav"), content = $("settings-content"); nav.innerHTML = "";
    Object.keys(SETTINGS).forEach((k, i) => {
      const b = document.createElement("button"); b.textContent = k; b.className = i === 0 ? "active" : "";
      b.onclick = () => { nav.querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b)); content.innerHTML = paneHTML(k); };
      nav.append(b);
    });
    content.innerHTML = paneHTML("Location");
  }

  document.querySelectorAll(".close-modal").forEach((b) => b.addEventListener("click", closeModals));
  layer().addEventListener("click", (e) => { if (e.target === layer()) closeModals(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModals(); });
  $("btn-theme").onclick = toggleTheme;
  $("btn-log").onclick = () => { renderSightings(); openModal("sightings-modal"); };
  $("btn-settings").onclick = () => { buildSettings(); openModal("settings-modal"); };
  $("cta-close").onclick = () => { $("cta-banner").hidden = true; };

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
