/* ====================================================================
   SkyWarden — front-end controller
   ==================================================================== */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const DRONE_SVG = '<svg class="glyph" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l2.4 4.8L20 8l-3.6 3.2L17 17l-5-2.6L7 17l.6-5.8L4 8l5.6-1.2z"/></svg>';
  const OP_SVG = '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><circle cx="12" cy="7" r="3.4"/><path d="M4.5 20c0-4.1 3.4-6.5 7.5-6.5s7.5 2.4 7.5 6.5z"/></svg>';

  const state = {
    cfg: null,
    map: null,
    home: null,
    homeMarker: null,
    rings: [],
    contacts: new Map(),   // drone_id -> contact object (LIVE)
    focused: null,
    mode: "live",          // "live" | "review"
    pickingHome: false,
    ws: null,
    review: null,          // review session object
  };

  const CONTACT_TTL = 30_000;   // drop a live contact after 30s of silence
  const INNER_RING = () => (state.cfg?.map?.range_rings_m?.[0] ?? 250);

  /* ---------------------------- boot ---------------------------- */
  async function boot() {
    state.cfg = await (await fetch("/api/config")).json();
    applyBrand(state.cfg.brand);
    state.home = state.cfg.site.home;
    initMap();
    wireUI();
    connectWS();
    tickClock();
    setInterval(tickClock, 1000);
    setInterval(pruneContacts, 3000);
    loadEvents();
  }

  function applyBrand(brand) {
    if (!brand) return;
    document.documentElement.style.setProperty("--accent", brand.accent);
    document.documentElement.style.setProperty("--accent-alt", brand.accent_alt);
    $("brandName").textContent = brand.product_name;
    $("brandTag").textContent = brand.tagline;
    $("nodeId").textContent = state.cfg.node_id;
    document.title = brand.product_name;
  }

  /* ---------------------------- map ---------------------------- */
  function initMap() {
    const m = state.cfg.map;
    state.map = L.map("map", { zoomControl: true, attributionControl: false })
      .setView([state.home.lat, state.home.lon], m.default_zoom);
    L.tileLayer(m.tile_url, { maxZoom: m.max_zoom }).addTo(state.map);
    drawHome();
    state.map.on("click", (e) => {
      if (state.pickingHome) setHomeFromLatLng(e.latlng.lat, e.latlng.lng);
    });
  }

  function homeIcon() {
    return L.divIcon({
      className: "", iconSize: [18, 18], iconAnchor: [9, 9],
      html: '<div style="width:16px;height:16px;border-radius:50%;background:#4aa8ff;'
          + 'box-shadow:0 0 0 4px rgba(74,168,255,.25),0 0 12px rgba(74,168,255,.8)"></div>',
    });
  }

  function drawHome() {
    state.rings.forEach((r) => r.remove());
    state.rings = [];
    if (state.homeMarker) state.homeMarker.remove();
    const { lat, lon } = state.home;
    state.homeMarker = L.marker([lat, lon], { icon: homeIcon() })
      .addTo(state.map).bindTooltip(state.home.label || "Home Base");
    (state.cfg.map.range_rings_m || []).forEach((r) => {
      state.rings.push(L.circle([lat, lon], {
        radius: r, color: "#4aa8ff", weight: 1, opacity: .35,
        fill: false, dashArray: "4 6",
      }).addTo(state.map));
    });
  }

  /* ---------------------------- websocket ---------------------------- */
  function connectWS() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    state.ws = ws;
    ws.onopen = () => setLink(true);
    ws.onclose = () => { setLink(false); setTimeout(connectWS, 2000); };
    ws.onerror = () => ws.close();
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.kind === "detection" && state.mode === "live") onDetection(msg);
    };
    // keepalive
    setInterval(() => { if (ws.readyState === 1) ws.send("ping"); }, 20000);
  }

  function setLink(up) {
    const pill = $("linkPill");
    pill.classList.toggle("live", up);
    pill.classList.toggle("down", !up);
    $("linkText").textContent = up ? "LIVE" : "OFFLINE";
  }

  /* ---------------------------- live detections ---------------------------- */
  function onDetection(d) {
    let c = state.contacts.get(d.drone_id);
    if (!c) { c = createContact(d); state.contacts.set(d.drone_id, c); }
    updateContact(c, d);
    renderContacts();
    maybeAlert(c, d);
  }

  function createContact(d) {
    const track = L.polyline([], { color: getComputedStyle(document.documentElement)
      .getPropertyValue("--accent").trim() || "#38e8b0", weight: 2, opacity: .7 })
      .addTo(state.map);
    return {
      id: d.drone_id, model: d.model, source: d.source,
      marker: null, opMarker: null, track, positions: [],
      last: d, lastSeen: Date.now(), altHist: [],
    };
  }

  function droneIcon(threat, heading) {
    return L.divIcon({
      className: "drone-marker" + (threat ? " threat" : ""),
      iconSize: [26, 26], iconAnchor: [13, 13],
      html: DRONE_SVG.replace("<svg ", `<svg style="transform:rotate(${heading || 0}deg)" `),
    });
  }
  function opIcon() {
    return L.divIcon({ className: "op-marker", iconSize: [22, 22], iconAnchor: [11, 11], html: OP_SVG });
  }

  function updateContact(c, d) {
    c.last = d; c.lastSeen = Date.now(); c.model = d.model || c.model;
    if (d.drone_lat != null) {
      const ll = [d.drone_lat, d.drone_lon];
      c.positions.push(ll);
      if (c.positions.length > 600) c.positions.shift();
      c.track.setLatLngs(c.positions);
      const threat = d.range_m != null && d.range_m <= INNER_RING();
      if (!c.marker) {
        c.marker = L.marker(ll, { icon: droneIcon(threat, d.heading_deg) })
          .addTo(state.map)
          .on("click", () => focusContact(c.id));
      } else {
        c.marker.setLatLng(ll);
        c.marker.setIcon(droneIcon(threat, d.heading_deg));
      }
      c.marker.bindTooltip(`${c.model || "Drone"} • ${fmtDist(d.range_m)}`,
        { permanent: false, direction: "top" });
      if (d.height_agl_m != null) { c.altHist.push(d.height_agl_m); if (c.altHist.length > 40) c.altHist.shift(); }
    }
    if (d.operator_lat != null) {
      const oll = [d.operator_lat, d.operator_lon];
      if (!c.opMarker) c.opMarker = L.marker(oll, { icon: opIcon() })
        .addTo(state.map).bindTooltip("Operator");
      else c.opMarker.setLatLng(oll);
    }
  }

  function pruneContacts() {
    if (state.mode !== "live") return;
    const now = Date.now();
    for (const [id, c] of state.contacts) {
      if (now - c.lastSeen > CONTACT_TTL) { removeContact(c); state.contacts.delete(id); }
    }
    renderContacts();
  }
  function removeContact(c) {
    [c.marker, c.opMarker, c.track].forEach((x) => x && x.remove());
  }

  /* ---------------------------- contact panel ---------------------------- */
  function renderContacts() {
    const list = $("contactList");
    const arr = [...state.contacts.values()].sort((a, b) =>
      (a.last.range_m ?? 9e9) - (b.last.range_m ?? 9e9));
    $("activeCount").textContent = arr.length;
    $("contactsEmpty").style.display = arr.length ? "none" : "";
    list.innerHTML = "";
    for (const c of arr) list.appendChild(contactCard(c));
  }

  function contactCard(c) {
    const d = c.last;
    const threat = d.range_m != null && d.range_m <= INNER_RING();
    const el = document.createElement("div");
    el.className = "contact" + (threat ? " threat" : "") + (state.focused === c.id ? " focused" : "");
    const opDist = operatorDistance(d);
    el.innerHTML = `
      <div class="contact-top">
        <span class="contact-model">${esc(c.model || "Unknown UA")}</span>
        <span class="contact-src">${esc(d.source || "")}</span>
      </div>
      <div class="contact-id">${esc(c.id)}</div>
      <div class="tel-grid">
        <div class="tel"><span class="v">${d.range_m != null ? fmtDist(d.range_m) : "—"}</span><span class="k">Range ${d.compass || ""}</span></div>
        <div class="tel"><span class="v">${num(d.height_agl_m)}<small>m</small></span><span class="k">Height</span></div>
        <div class="tel"><span class="v">${num(d.speed_mps)}<small>m/s</small></span><span class="k">Speed</span></div>
        <div class="tel"><span class="v">${num(d.heading_deg)}<small>°</small></span><span class="k">Heading</span></div>
        <div class="tel"><span class="v">${num(d.vspeed_mps)}<small>m/s</small></span><span class="k">V-Speed</span></div>
        <div class="tel"><span class="v">${d.rssi != null ? Math.round(d.rssi) : "—"}</span><span class="k">RSSI</span></div>
      </div>
      ${opDist ? `<div class="contact-op">◎ Operator located ${opDist}</div>` : ""}`;
    el.onclick = () => focusContact(c.id);
    return el;
  }

  function focusContact(id) {
    state.focused = id;
    const c = state.contacts.get(id) || (state.review && state.review.contacts.get(id));
    if (c && c.last && c.last.drone_lat != null) state.map.panTo([c.last.drone_lat, c.last.drone_lon]);
    renderContacts();
  }

  function operatorDistance(d) {
    if (d.operator_lat == null || !state.home) return null;
    const m = haversine(state.home.lat, state.home.lon, d.operator_lat, d.operator_lon);
    return `${fmtDist(m)} from base`;
  }

  /* ---------------------------- alerts ---------------------------- */
  let alertTimer = null;
  function maybeAlert(c, d) {
    if (d.range_m != null && d.range_m <= INNER_RING()) {
      const b = $("alertBanner");
      $("alertText").textContent =
        `⚠ ${c.model || "Drone"} within ${fmtDist(d.range_m)} of ${state.home.label || "Home Base"} — bearing ${d.compass || d.bearing_deg + "°"}`;
      b.hidden = false;
      clearTimeout(alertTimer);
      alertTimer = setTimeout(() => (b.hidden = true), 8000);
    }
  }

  /* ---------------------------- sighting log ---------------------------- */
  async function loadEvents() {
    try {
      const { events } = await (await fetch("/api/events?days=30")).json();
      const list = $("eventList");
      list.innerHTML = "";
      for (const e of events.slice(0, 60)) list.appendChild(eventRow(e));
    } catch (_) { /* ignore */ }
  }
  function eventRow(e) {
    const el = document.createElement("div");
    el.className = "event";
    const dur = Math.max(1, Math.round((e.last_seen - e.first_seen)));
    el.innerHTML = `
      <div class="event-title"><b>${esc(e.model || e.drone_id)}</b><span class="event-meta">${clockOf(e.last_seen)}</span></div>
      <div class="event-meta">${esc(e.drone_id)}</div>
      <div class="event-meta">${fmtDur(dur)} · max ${Math.round(e.max_alt_m)}m · ${e.count} hits${e.operator_lat != null ? " · operator logged" : ""}</div>`;
    return el;
  }

  /* ---------------------------- review / playback ---------------------------- */
  function enterReview() {
    state.mode = "review";
    $("btnReview").classList.add("active"); $("btnLive").classList.remove("active");
    $("pbControls").hidden = false;
    // hide live layers
    for (const c of state.contacts.values()) removeContact(c);
    loadReviewWindow();
  }
  function enterLive() {
    state.mode = "live";
    $("btnLive").classList.add("active"); $("btnReview").classList.remove("active");
    $("pbControls").hidden = true;
    stopPlay();
    if (state.review) { state.review.contacts.forEach(removeContact); state.review = null; }
    renderContacts();
  }

  async function loadReviewWindow() {
    stopPlay();
    const win = parseInt($("pbWindow").value, 10);
    const end = Date.now() / 1000;
    const start = end - win;
    const { detections } = await (await fetch(`/api/detections?start=${start}&end=${end}`)).json();
    const contacts = new Map();
    for (const d of detections) {
      if (!contacts.has(d.drone_id)) contacts.set(d.drone_id, { id: d.drone_id, model: d.model, rows: [] });
      contacts.get(d.drone_id).rows.push(d);
    }
    if (state.review) state.review.contacts.forEach(removeContact);
    state.review = { start, end, detections, contacts, playhead: start, playing: false, layers: new Map() };
    $("scrubber").value = 1000;
    renderReviewAt(end);
    $("pbTime").textContent = detections.length
      ? `${clockOf(start)} — ${clockOf(end)}  (${detections.length} pts)`
      : "No data in this window";
  }

  function renderReviewAt(t) {
    if (!state.review) return;
    const active = [];
    for (const [id, c] of state.review.contacts) {
      const rows = c.rows.filter((r) => r.ts <= t);
      let layer = state.review.layers.get(id);
      if (!layer) {
        layer = { track: L.polyline([], { color: "#38e8b0", weight: 2, opacity: .7 }).addTo(state.map), marker: null, op: null };
        state.review.layers.set(id, layer);
      }
      const pts = rows.filter((r) => r.drone_lat != null).map((r) => [r.drone_lat, r.drone_lon]);
      layer.track.setLatLngs(pts);
      const last = rows[rows.length - 1];
      const recent = last && (t - last.ts) < 15;    // consider "in the air" if seen in last 15s of timeline
      if (recent && last.drone_lat != null) {
        if (!layer.marker) layer.marker = L.marker([last.drone_lat, last.drone_lon], { icon: droneIcon(false, last.heading_deg) }).addTo(state.map);
        else { layer.marker.setLatLng([last.drone_lat, last.drone_lon]); layer.marker.setIcon(droneIcon(false, last.heading_deg)); }
        layer.marker.bindTooltip(`${c.model || "Drone"} • ${clockOf(last.ts)}`);
        if (last.operator_lat != null) {
          if (!layer.op) layer.op = L.marker([last.operator_lat, last.operator_lon], { icon: opIcon() }).addTo(state.map);
          else layer.op.setLatLng([last.operator_lat, last.operator_lon]);
        }
        active.push({ id, model: c.model, last: annotate(last) });
      } else if (layer.marker) { layer.marker.remove(); layer.marker = null; if (layer.op) { layer.op.remove(); layer.op = null; } }
    }
    // reuse contact panel for the review frame
    const list = $("contactList"); list.innerHTML = "";
    $("activeCount").textContent = active.length;
    $("contactsEmpty").style.display = active.length ? "none" : "";
    active.sort((a, b) => (a.last.range_m ?? 9e9) - (b.last.range_m ?? 9e9));
    for (const c of active) list.appendChild(contactCard({ id: c.id, model: c.model, last: c.last }));
    $("pbTime").textContent = `${clockOf(t)}`;
  }

  function annotate(d) {
    const o = { ...d };
    if (d.drone_lat != null && state.home) {
      o.range_m = Math.round(haversine(state.home.lat, state.home.lon, d.drone_lat, d.drone_lon));
      const brg = bearing(state.home.lat, state.home.lon, d.drone_lat, d.drone_lon);
      o.bearing_deg = Math.round(brg); o.compass = compass16(brg);
    }
    return o;
  }

  let playRAF = null, lastFrame = 0;
  function togglePlay() { state.review && (state.review.playing ? stopPlay() : startPlay()); }
  function startPlay() {
    if (!state.review) return;
    state.review.playing = true; $("btnPlay").textContent = "❚❚";
    if (state.review.playhead >= state.review.end) state.review.playhead = state.review.start;
    lastFrame = performance.now();
    const step = (now) => {
      if (!state.review || !state.review.playing) return;
      const speed = parseFloat($("pbSpeed").value);
      const dt = (now - lastFrame) / 1000; lastFrame = now;
      state.review.playhead = Math.min(state.review.end, state.review.playhead + dt * speed);
      const frac = (state.review.playhead - state.review.start) / (state.review.end - state.review.start);
      $("scrubber").value = Math.round(frac * 1000);
      renderReviewAt(state.review.playhead);
      if (state.review.playhead >= state.review.end) return stopPlay();
      playRAF = requestAnimationFrame(step);
    };
    playRAF = requestAnimationFrame(step);
  }
  function stopPlay() {
    if (playRAF) cancelAnimationFrame(playRAF);
    playRAF = null;
    if (state.review) state.review.playing = false;
    $("btnPlay").textContent = "▶";
  }

  /* ---------------------------- settings / home ---------------------------- */
  function openSettings() {
    $("homeLat").value = state.home.lat.toFixed(5);
    $("homeLon").value = state.home.lon.toFixed(5);
    $("homeLabel").value = state.home.label || "Home Base";
    $("settingsModal").hidden = false;
  }
  function closeSettings() { $("settingsModal").hidden = true; state.pickingHome = false; }
  function setHomeFromLatLng(lat, lon) {
    $("homeLat").value = lat.toFixed(5); $("homeLon").value = lon.toFixed(5);
    $("homeHint").textContent = `Picked ${lat.toFixed(5)}, ${lon.toFixed(5)} — press Save.`;
    state.pickingHome = false;
    $("settingsModal").hidden = false;
  }
  async function saveHome() {
    const lat = parseFloat($("homeLat").value), lon = parseFloat($("homeLon").value);
    if (Number.isNaN(lat) || Number.isNaN(lon)) return;
    const label = $("homeLabel").value.trim() || "Home Base";
    const res = await (await fetch("/api/home", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat, lon, label }),
    })).json();
    state.home = { ...state.home, ...res.home };
    state.cfg.site.home = state.home;
    drawHome();
    state.map.panTo([lat, lon]);
    closeSettings();
  }

  /* ---------------------------- UI wiring ---------------------------- */
  function wireUI() {
    $("btnSettings").onclick = openSettings;
    $("btnCloseSettings").onclick = closeSettings;
    $("btnSaveHome").onclick = saveHome;
    $("btnUseMap").onclick = () => { state.pickingHome = true; $("settingsModal").hidden = true;
      $("homeHint").textContent = "Click the map to drop the marker…"; };
    $("btnLive").onclick = enterLive;
    $("btnReview").onclick = enterReview;
    $("btnPlay").onclick = togglePlay;
    $("btnRefreshEvents").onclick = loadEvents;
    $("pbWindow").onchange = loadReviewWindow;
    $("scrubber").oninput = (e) => {
      if (!state.review) return;
      stopPlay();
      const frac = e.target.value / 1000;
      state.review.playhead = state.review.start + frac * (state.review.end - state.review.start);
      renderReviewAt(state.review.playhead);
    };
  }

  /* ---------------------------- utils ---------------------------- */
  function tickClock() { $("clock").textContent = new Date().toLocaleTimeString(); }
  function clockOf(ts) { return new Date(ts * 1000).toLocaleTimeString(); }
  function num(v) { return v == null ? "—" : (Math.round(v * 10) / 10); }
  function esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  function fmtDist(m) { if (m == null) return "—"; return m >= 1000 ? (m / 1000).toFixed(2) + " km" : Math.round(m) + " m"; }
  function fmtDur(s) { const m = Math.floor(s / 60), r = s % 60; return m ? `${m}m ${r}s` : `${r}s`; }

  const R = 6371000, rad = (d) => d * Math.PI / 180;
  function haversine(a, b, c, d) {
    const p1 = rad(a), p2 = rad(c), dp = rad(c - a), dl = rad(d - b);
    const x = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(x));
  }
  function bearing(a, b, c, d) {
    const p1 = rad(a), p2 = rad(c), dl = rad(d - b);
    const y = Math.sin(dl) * Math.cos(p2);
    const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
  }
  const DIRS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  function compass16(b) { return DIRS[Math.round(b / 22.5) % 16]; }

  boot();
})();
