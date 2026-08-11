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
    initTheme();
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
    renderWordmark(brand.product_name);
    $("brandTag").textContent = brand.tagline;
    $("nodeId").textContent = state.cfg.node_id;
    document.title = brand.product_name;
  }

  /** Two-tone the wordmark like the logo: "Drone" + "Dingo". */
  function renderWordmark(name) {
    const el = $("brandName");
    el.textContent = "";
    const m = /^([A-Z][a-z]+)([A-Z].*)$/.exec(name || "");
    if (m) {
      const a = document.createElement("span"); a.className = "b1"; a.textContent = m[1];
      const b = document.createElement("span"); b.className = "b2"; b.textContent = m[2];
      el.append(a, b);
    } else {
      el.textContent = name || "";
    }
  }

  /* ---------------------------- theme ---------------------------- */
  function initTheme() {
    const saved = localStorage.getItem("dd-theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);
    updateThemeButton();
  }
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme")
      || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  }
  function toggleTheme() {
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("dd-theme", next);
    updateThemeButton();
    if (window.DDMap) DDMap.setTheme(next);   // re-tone the basemap
  }
  function updateThemeButton() {
    const b = $("btnTheme");
    if (b) b.textContent = currentTheme() === "dark" ? "☀" : "☾";
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

  /* ---------------------------- admin panel ---------------------------- */
  function openSettings(tab) {
    $("homeLat").value = Number(state.home.lat).toFixed(5);
    $("homeLon").value = Number(state.home.lon).toFixed(5);
    $("homeLabel").value = state.home.label || "Home Base";
    $("settingsModal").hidden = false;
    showTab(tab || "location");
  }
  function closeSettings() { $("settingsModal").hidden = true; state.pickingHome = false; }

  function showTab(name) {
    document.querySelectorAll(".admin-tab").forEach((b) =>
      b.classList.toggle("active", b.dataset.tab === name));
    document.querySelectorAll(".admin-pane").forEach((p) =>
      p.classList.toggle("active", p.dataset.pane === name));
    if (name === "alerts") loadAlertsForm();
    else if (name === "system") loadSystem();
    else if (name === "network") loadNetwork();
    else if (name === "updates") checkUpdate();
  }

  /* ---- Alerts (editable) ---- */
  async function loadAlertsForm() {
    try {
      const a = await (await fetch("/api/alerts/config")).json();
      $("aNtfyTopic").value = a.ntfy_topic || "";
      $("aNtfyServer").value = a.ntfy_server || "";
      $("aWebhook").value = a.webhook_url || "";
      $("aRing").value = a.alert_ring_m ?? "";
      $("aResight").value = a.resight_after_s ?? "";
      $("aQuiet").value = a.quiet_hours || "";
      $("aQuietSuppress").checked = !!a.quiet_hours_suppress;
    } catch (_) {}
  }
  async function saveAlerts() {
    const body = {
      ntfy_topic: $("aNtfyTopic").value.trim(),
      ntfy_server: $("aNtfyServer").value.trim(),
      webhook_url: $("aWebhook").value.trim(),
      alert_ring_m: $("aRing").value, resight_after_s: $("aResight").value,
      quiet_hours: $("aQuiet").value.trim(),
      quiet_hours_suppress: $("aQuietSuppress").checked,
    };
    const el = $("alertStatus"); el.textContent = "Saving…";
    try {
      await fetch("/api/alerts/config", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      el.className = "small alert-ok"; el.textContent = "Saved.";
    } catch (_) { el.className = "small alert-off"; el.textContent = "Save failed."; }
  }
  async function sendTestAlert() {
    const el = $("alertStatus"); el.textContent = "Sending…";
    try {
      const r = await (await fetch("/api/alerts/test", { method: "POST" })).json();
      el.className = "small " + (r.ok ? "alert-ok" : "alert-off");
      el.textContent = r.ok ? "Test sent — check your phone." : `Failed: ${r.error}`;
    } catch (_) { el.className = "small alert-off"; el.textContent = "Failed to send."; }
  }

  /* ---- System ---- */
  const fmtBytes = (b) => b == null ? "—"
    : b >= 1e9 ? (b / 1073741824).toFixed(1) + " GB" : (b / 1048576).toFixed(0) + " MB";
  const fmtUptime = (s) => {
    if (s == null) return "—";
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
  };
  function setBar(id, pct, warnAt, hotAt) {
    const el = $(id); if (!el) return;
    const p = Math.max(0, Math.min(100, pct || 0));
    el.style.width = p + "%";
    el.classList.toggle("warn", hotAt ? p >= warnAt && p < hotAt : p >= warnAt);
    if (hotAt) el.classList.toggle("hot", p >= hotAt);
  }
  async function loadSystem() {
    try {
      const s = await (await fetch("/api/system/status")).json();
      $("sHost").textContent = s.hostname || "—";
      $("sModel").textContent = s.pi_model || "—";
      $("sUptime").textContent = fmtUptime(s.uptime_s);
      $("sSvc").textContent = s.service || "—";
      $("sSvc").style.color = s.service === "active" ? "var(--accent-alt)"
        : (s.service === "n/a" ? "" : "var(--danger)");

      // Throttle banner (Pi-only).
      const t = s.throttle, tb = $("sThrottle");
      if (!t) { tb.hidden = true; }
      else if (t.healthy) {
        tb.hidden = false; tb.className = "throttle ok";
        tb.textContent = "Power & thermal healthy — no throttling.";
      } else {
        tb.hidden = false; tb.className = "throttle warn";
        const now = t.active_now.map((x) => `<b>${esc(x)}</b>`);
        const past = t.since_boot.map((x) => esc(x));
        tb.innerHTML = [...now, ...past].join("<br>")
          || "Throttling flags set (" + esc(t.value) + ")";
      }

      // Bars.
      const mem = s.memory && s.memory.total ? s.memory.percent : 0;
      setBar("sMemBar", mem, 75, 90);
      $("sMem").textContent = s.memory && s.memory.total
        ? `${mem}% of ${fmtBytes(s.memory.total)}` : "—";

      const loadPct = s.load && s.cpu_count ? (s.load[0] / s.cpu_count) * 100 : 0;
      setBar("sLoadBar", loadPct, 70, 100);
      $("sLoad").textContent = s.load ? s.load.join("  ") : "—";

      const temp = s.cpu_temp_c || 0;
      setBar("sTempBar", (temp / 85) * 100, 65 / 85 * 100, 80 / 85 * 100);
      $("sTemp").textContent = s.cpu_temp_c != null ? s.cpu_temp_c + " °C" : "—";

      const d = s.disk;
      setBar("sDiskBar", d ? d.percent : 0, 80, 92);
      $("sDisk").textContent = d
        ? `${d.percent}% — ${fmtBytes(d.used)} of ${fmtBytes(d.total)}` : "—";
    } catch (_) {}
  }
  async function doReboot() {
    if (!confirm("Reboot the appliance now? Detection will stop for ~1 minute.")) return;
    await fetch("/api/system/reboot", { method: "POST" });
    setLink(false);
  }

  /* ---- Network ---- */
  async function loadNetwork() {
    try {
      const n = await (await fetch("/api/system/network")).json();
      const box = $("netInterfaces");
      box.innerHTML = n.interfaces.length ? "" : '<p class="muted small">No interfaces reported (Linux-only).</p>';
      const ethSel = $("ethIface"); ethSel.innerHTML = "";
      for (const itf of n.interfaces) {
        const row = document.createElement("div"); row.className = "net-row";
        row.innerHTML = `<span><span class="ssid">${esc(itf.name)}</span> `
          + `<span class="meta">${esc(itf.type)} · ${itf.state}</span></span>`
          + `<span class="meta">${esc((itf.addresses || []).join(", ") || "—")}</span>`;
        box.appendChild(row);
        if (itf.type === "ethernet") {
          const o = document.createElement("option");
          o.value = itf.name; o.textContent = itf.name; ethSel.appendChild(o);
        }
      }
      if (!ethSel.children.length) {
        const o = document.createElement("option"); o.textContent = "No ethernet"; o.value = "";
        ethSel.appendChild(o);
      }
      $("wifiCurrent").textContent = n.wifi ? `Connected: ${n.wifi.name}` : "Not connected to Wi-Fi.";
    } catch (_) {}
  }
  async function applyEthernet() {
    const body = {
      iface: $("ethIface").value, mode: $("ethMode").value,
      ip: $("ethIp").value.trim(), gateway: $("ethGw").value.trim(),
      dns: $("ethDns").value.trim(),
    };
    const el = $("ethStatus"); el.textContent = "Applying…";
    try {
      const r = await (await fetch("/api/system/ethernet", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) })).json();
      el.className = "small " + (r.ok ? "alert-ok" : "alert-off");
      el.textContent = r.message || (r.ok ? "Applied." : "Failed.");
      if (r.ok) loadNetwork();
    } catch (_) { el.className = "small alert-off"; el.textContent = "Failed."; }
  }
  async function wifiScan() {
    const list = $("wifiList"); list.innerHTML = '<p class="muted small">Scanning…</p>';
    try {
      const r = await (await fetch("/api/system/wifi/scan")).json();
      list.innerHTML = r.networks.length ? "" : '<p class="muted small">No networks found.</p>';
      for (const net of r.networks) {
        const row = document.createElement("div"); row.className = "net-row";
        row.innerHTML = `<span><span class="ssid">${esc(net.ssid)}</span> `
          + `<span class="meta">${esc(net.security)}</span></span>`
          + `<span class="wifi-bars">${net.signal}%</span>`;
        const btn = document.createElement("button"); btn.className = "btn ghost";
        btn.textContent = net.active ? "Connected" : "Join"; btn.disabled = net.active;
        btn.onclick = () => promptWifi(net.ssid);
        row.appendChild(btn); list.appendChild(row);
      }
    } catch (_) { list.innerHTML = '<p class="muted small">Scan failed.</p>'; }
  }
  function promptWifi(ssid) {
    $("wifiSsid").textContent = ssid; $("wifiPass").value = "";
    $("wifiConnect").hidden = false; $("wifiPass").focus();
  }
  async function wifiJoin() {
    const ssid = $("wifiSsid").textContent, password = $("wifiPass").value;
    $("netStatus").textContent = `Connecting to ${ssid}…`;
    try {
      const r = await (await fetch("/api/system/wifi/connect", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ssid, password }) })).json();
      $("netStatus").textContent = r.message || (r.ok ? "Connected." : "Failed.");
      if (r.ok) { $("wifiConnect").hidden = true; loadNetwork(); }
    } catch (_) { $("netStatus").textContent = "Connection failed."; }
  }

  /* ---- Updates ---- */
  async function checkUpdate() {
    const el = $("ddUpdateStatus"); el.textContent = "Checking…";
    $("btnInstallUpdate").hidden = true;
    try {
      const u = await (await fetch("/api/update/check")).json();
      el.className = "small " + (u.available ? "update-available" : "muted");
      el.textContent = u.message + (u.build ? `  (build ${u.build})` : "");
      if (u.notes) { $("updateLog").hidden = false; $("updateLog").textContent = u.notes; }
      $("btnInstallUpdate").hidden = !u.available;
    } catch (_) { el.textContent = "Update check failed."; }
  }
  async function installUpdate() {
    if (!confirm("Install the update and restart DroneDingo now?")) return;
    const el = $("ddUpdateStatus"); el.textContent = "Installing… the service will restart.";
    $("btnInstallUpdate").disabled = true;
    try {
      const r = await (await fetch("/api/update/install", { method: "POST" })).json();
      $("updateLog").hidden = false; $("updateLog").textContent = r.output || r.message;
      el.textContent = r.message;
    } catch (_) {
      el.textContent = "Reconnecting after restart…";
      setTimeout(() => location.reload(), 8000);
    } finally { $("btnInstallUpdate").disabled = false; }
  }
  async function checkOS() {
    const el = $("osUpdateStatus"); el.textContent = "Checking… this can take a minute.";
    $("btnInstallOS").hidden = true;
    try {
      const r = await (await fetch("/api/update/os/check")).json();
      el.className = "small " + (r.upgradable ? "update-available" : "muted");
      el.textContent = r.message;
      $("btnInstallOS").hidden = !r.upgradable;
    } catch (_) { el.textContent = "OS update check failed."; }
  }
  async function installOS() {
    if (!confirm("Install operating-system updates now? This can take several minutes.")) return;
    const el = $("osUpdateStatus"); el.textContent = "Installing OS updates…";
    $("btnInstallOS").disabled = true;
    try {
      const r = await (await fetch("/api/update/os/install", { method: "POST" })).json();
      el.textContent = r.message;
    } catch (_) { el.textContent = "OS update failed."; }
    finally { $("btnInstallOS").disabled = false; }
  }

  /* ---- Account ---- */
  async function changePassword() {
    const el = $("pwStatus");
    try {
      const r = await fetch("/api/auth/password", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current: $("pwCurrent").value, new: $("pwNew").value }) });
      const d = await r.json();
      el.className = "small " + (d.ok ? "alert-ok" : "alert-off");
      el.textContent = d.ok ? "Password updated." : (d.error || "Failed.");
      if (d.ok) { $("pwCurrent").value = ""; $("pwNew").value = ""; }
    } catch (_) { el.className = "small alert-off"; el.textContent = "Failed."; }
  }
  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    location.href = "/login";
  }

  /* ---------------------------- About ---------------------------- */
  async function openAbout() {
    $("aboutModal").hidden = false;
    try {
      const a = await (await fetch("/api/about")).json();
      renderWordmarkInto($("aboutName"), a.brand.product_name);
      $("aboutTag").textContent = a.brand.tagline || "";
      $("aboutVersion").textContent = a.version.version || "—";
      $("aboutBuild").textContent = a.version.build || a.version.channel || "—";
      $("aboutNode").textContent = a.node_id || "—";
      $("aboutCopyright").textContent = a.brand.copyright || "";
    } catch (_) {}
  }
  function renderWordmarkInto(el, name) {
    el.textContent = "";
    const m = /^([A-Z][a-z]+)([A-Z].*)$/.exec(name || "");
    if (m) {
      const a = document.createElement("span"); a.className = "b1"; a.textContent = m[1];
      const b = document.createElement("span"); b.className = "b2"; b.textContent = m[2];
      el.append(a, b);
    } else { el.textContent = name || ""; }
  }
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
    $("btnSettings").onclick = () => openSettings();
    $("btnCloseSettings").onclick = closeSettings;
    $("btnSaveHome").onclick = saveHome;
    $("btnTheme").onclick = toggleTheme;
    $("btnAbout").onclick = openAbout;
    $("btnCloseAbout").onclick = () => { $("aboutModal").hidden = true; };
    $("aboutToUpdates").onclick = (e) => {
      e.preventDefault(); $("aboutModal").hidden = true; openSettings("updates");
    };
    // admin tabs
    document.querySelectorAll(".admin-tab").forEach((b) =>
      b.onclick = () => showTab(b.dataset.tab));
    // alerts
    $("btnTestAlert").onclick = sendTestAlert;
    $("btnSaveAlerts").onclick = saveAlerts;
    // system
    $("btnRefreshSys").onclick = loadSystem;
    $("btnReboot").onclick = doReboot;
    // network
    $("btnWifiScan").onclick = wifiScan;
    $("btnWifiJoin").onclick = wifiJoin;
    $("btnWifiCancel").onclick = () => { $("wifiConnect").hidden = true; };
    $("btnEthApply").onclick = applyEthernet;
    $("ethMode").onchange = () => { $("ethStatic").hidden = $("ethMode").value !== "static"; };
    // updates
    $("btnCheckUpdate").onclick = checkUpdate;
    $("btnInstallUpdate").onclick = installUpdate;
    $("btnCheckOS").onclick = checkOS;
    $("btnInstallOS").onclick = installOS;
    // account
    $("btnChangePw").onclick = changePassword;
    $("btnLogout").onclick = logout;
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
