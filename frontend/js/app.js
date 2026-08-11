/* ====================================================================
   DroneDingo — front-end controller
   ==================================================================== */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const state = {
    cfg: null,
    home: null,
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
    await initMap();
    wireUI();
    connectWS();
    tickClock();
    setInterval(tickClock, 1000);
    setInterval(pruneContacts, 3000);
    loadEvents();
  }

  function applyBrand(brand) {
    if (!brand) return;
    const root = document.documentElement;
    for (const [key, varName] of [["accent", "--accent"],
                                  ["accent_alt", "--accent-alt"],
                                  ["home", "--home"],
                                  ["danger", "--danger"]]) {
      if (brand[key]) root.style.setProperty(varName, brand[key]);
    }
    $("brandName").textContent = brand.product_name;
    $("brandTag").textContent = brand.tagline;
    $("nodeId").textContent = state.cfg.node_id;
    document.title = brand.product_name;
  }

  /** Read a themed colour so canvas/SVG layers match the CSS palette. */
  function themeColor(name, fallback) {
    return getComputedStyle(document.documentElement)
      .getPropertyValue(name).trim() || fallback;
  }

  /* ---------------------------- map ---------------------------- */
  async function initMap() {
    await DDMap.init({
      container: "map",
      center: { lat: state.home.lat, lon: state.home.lon },
      zoom: state.cfg.map.default_zoom,
      onClick: (lat, lon) => {
        if (state.pickingHome) setHomeFromLatLng(lat, lon);
      },
    });
    drawHome();
    showBasemapInfo();
  }

  function drawHome() {
    DDMap.setHome(state.home.lat, state.home.lon, state.home.label,
                  state.cfg.map.range_rings_m || []);
  }

  /** Note in the legend whether the map is running offline. */
  async function showBasemapInfo() {
    try {
      const info = await (await fetch("/api/map/info")).json();
      const el = $("basemapInfo");
      if (!el) return;
      el.textContent = info.offline
        ? `Offline basemap · ${info.vector ? "vector" : "raster"}`
        : "Online basemap";
      el.classList.toggle("offline-ok", !!info.offline);
    } catch (_) { /* non-critical */ }
  }

  /* ---------------------------- websocket ---------------------------- */
  function connectWS() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    state.ws = ws;
    // One keepalive per socket, cleared on close — otherwise reconnects on a
    // flaky link accumulate timers for the life of the page.
    let keepalive = null;
    const shutdown = () => {
      if (keepalive) { clearInterval(keepalive); keepalive = null; }
    };
    ws.onopen = () => {
      setLink(true);
      keepalive = setInterval(() => {
        if (ws.readyState === 1) ws.send("ping");
      }, 20000);
    };
    ws.onclose = () => { shutdown(); setLink(false); setTimeout(connectWS, 2000); };
    ws.onerror = () => ws.close();
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.kind === "detection" && state.mode === "live") onDetection(msg);
    };
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
    return {
      id: d.drone_id, model: d.model, source: d.source,
      positions: [], last: d, lastSeen: Date.now(), altHist: [],
    };
  }

  function updateContact(c, d) {
    c.last = d; c.lastSeen = Date.now(); c.model = d.model || c.model;
    if (d.drone_lat != null) {
      c.positions.push([d.drone_lat, d.drone_lon]);
      if (c.positions.length > 600) c.positions.shift();
      DDMap.setTrack(c.id, c.positions);
      const threat = d.range_m != null && d.range_m <= INNER_RING();
      DDMap.upsertDrone(c.id, d.drone_lat, d.drone_lon, d.heading_deg, threat,
                        `${c.model || "Drone"} • ${fmtDist(d.range_m)}`,
                        focusContact);
      if (d.height_agl_m != null) {
        c.altHist.push(d.height_agl_m);
        if (c.altHist.length > 40) c.altHist.shift();
      }
    }
    if (d.operator_lat != null) {
      DDMap.upsertOperator(c.id, d.operator_lat, d.operator_lon);
    }
  }

  function pruneContacts() {
    if (state.mode !== "live") return;
    const now = Date.now();
    for (const [id, c] of state.contacts) {
      if (now - c.lastSeen > CONTACT_TTL) {
        DDMap.removeContact(id);
        state.contacts.delete(id);
      }
    }
    renderContacts();
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
    const c = state.contacts.get(id)
      || (state.review && state.review.contacts.get(id));
    const last = c && (c.last || (c.rows && c.rows[c.rows.length - 1]));
    if (last && last.drone_lat != null) DDMap.panTo(last.drone_lat, last.drone_lon);
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
    DDMap.clearContacts();          // drop the live overlay
    state.contacts.clear();
    loadReviewWindow();
  }
  function enterLive() {
    state.mode = "live";
    $("btnLive").classList.add("active"); $("btnReview").classList.remove("active");
    $("pbControls").hidden = true;
    stopPlay();
    DDMap.clearContacts();
    state.review = null;
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
    DDMap.clearContacts();
    state.review = { start, end, detections, contacts,
                     playhead: start, playing: false };
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
      const pts = rows.filter((r) => r.drone_lat != null)
                      .map((r) => [r.drone_lat, r.drone_lon]);
      DDMap.setTrack(id, pts);
      const last = rows[rows.length - 1];
      // Treat a contact as "in the air" if seen in the last 15s of timeline.
      const recent = last && (t - last.ts) < 15;
      if (recent && last.drone_lat != null) {
        DDMap.upsertDrone(id, last.drone_lat, last.drone_lon, last.heading_deg,
                          false, `${c.model || "Drone"} • ${clockOf(last.ts)}`,
                          focusContact);
        if (last.operator_lat != null) {
          DDMap.upsertOperator(id, last.operator_lat, last.operator_lon);
        }
        active.push({ id, model: c.model, last: annotate(last) });
      } else {
        DDMap.hideMarkers(id);      // keep the track, drop the aircraft
      }
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
    $("homeLat").value = Number(state.home.lat).toFixed(5);
    $("homeLon").value = Number(state.home.lon).toFixed(5);
    $("homeLabel").value = state.home.label || "Home Base";
    $("settingsModal").hidden = false;
    loadAlertStatus();
  }

  async function loadAlertStatus() {
    const el = $("alertStatus");
    try {
      const a = await (await fetch("/api/alerts")).json();
      if (a.enabled) {
        const via = [a.ntfy_topic ? `ntfy topic “${a.ntfy_topic}”` : null,
                     a.webhook ? "webhook" : null].filter(Boolean).join(" + ");
        el.className = "small alert-ok";
        el.textContent = `Active — ${via}. Alerts fire within ${a.alert_ring_m} m, `
          + `at most once per drone every ${Math.round(a.resight_after_s / 60)} min.`;
      } else {
        el.className = "small alert-off";
        el.textContent = "Not configured. Set alerts.ntfy_topic in "
          + "config/dronedingo.yaml and restart to get phone notifications.";
      }
    } catch (_) { el.textContent = "Status unavailable."; }
  }

  async function sendTestAlert() {
    const el = $("alertStatus");
    el.textContent = "Sending…";
    try {
      const r = await (await fetch("/api/alerts/test", { method: "POST" })).json();
      el.className = "small " + (r.ok ? "alert-ok" : "alert-off");
      el.textContent = r.ok ? "Test alert sent — check your phone."
                            : `Failed: ${r.error}`;
    } catch (e) { el.className = "small alert-off"; el.textContent = "Failed to send."; }
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
    DDMap.panTo(lat, lon);
    closeSettings();
  }

  /* ---------------------------- UI wiring ---------------------------- */
  function wireUI() {
    $("btnSettings").onclick = openSettings;
    $("btnCloseSettings").onclick = closeSettings;
    $("btnSaveHome").onclick = saveHome;
    $("btnTestAlert").onclick = sendTestAlert;
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
