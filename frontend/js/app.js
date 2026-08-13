/* ====================================================================
   DroneDingo — front-end controller (liquid-glass shell + real backend).
   Drives the concept DOM with live detections, the real MapLibre map,
   the appliance API, auth, and the DroneDingo logo/theme.
   ==================================================================== */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);

  const ICON_DRONE = '<svg viewBox="0 0 24 24" fill="currentColor">'
    + '<path d="M12 2.6l1.6 3H10.4z"/>'
    + '<line x1="7" y1="7" x2="17" y2="17" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>'
    + '<line x1="17" y1="7" x2="7" y2="17" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>'
    + '<circle cx="5.6" cy="5.6" r="2.7"/><circle cx="18.4" cy="5.6" r="2.7"/>'
    + '<circle cx="5.6" cy="18.4" r="2.7"/><circle cx="18.4" cy="18.4" r="2.7"/>'
    + '<rect x="9.3" y="9.3" width="5.4" height="5.4" rx="1.5"/></svg>';
  const ICON_OP = '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="8" r="3.4"/>'
    + '<path d="M5 20c0-4 3.2-6.4 7-6.4s7 2.4 7 6.4z"/></svg>';
  // Unidentified, no-telemetry contact (e.g. RF presence with no Remote ID).
  const ICON_UFO = '<svg viewBox="0 0 24 24" fill="currentColor">'
    + '<ellipse cx="12" cy="12" rx="9" ry="3.4"/>'
    + '<path d="M8.2 10.7a3.8 2.9 0 0 1 7.6 0z"/>'
    + '<circle cx="6.6" cy="16.8" r=".9"/><circle cx="12" cy="18.3" r=".9"/><circle cx="17.4" cy="16.8" r=".9"/></svg>';
  // A contact with no position fix (RF presence only) is "unidentified".
  const isUnid = (d) => d && d.drone_lat == null;

  const state = {
    cfg: null, home: null, node: "—",
    contacts: new Map(),        // drone_id -> {last, positions[], lastSeen}
    ws: null, mode: "live",
    pickingHome: false,
    events: [], page: 0,
    review: null,
  };
  const TTL = 30_000;
  const INNER = () => (state.cfg?.map?.range_rings_m?.[0] ?? 250);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmtDist = (m) => m == null ? "—"
    : m >= 1000 ? (m / 1000).toFixed(2) + " km" : Math.round(m) + " m";
  const num = (v, u = "") => v == null ? "—" : (Math.round(v * 10) / 10) + u;

  /* ------------------------------ boot ------------------------------ */
  async function boot() {
    initTheme();
    const who = await fetch("/api/auth/whoami").then(r => r.ok ? r.json() : null).catch(() => null);
    if (!who || !who.email) { location.href = "/login"; return; }

    state.cfg = await (await fetch("/api/config")).json();
    state.home = state.cfg.site.home;
    state.node = state.cfg.node_id;
    applyBrand(state.cfg.brand);
    $("node-id").textContent = state.node;

    await DDMap.init({
      container: "map",
      center: { lat: state.home.lat, lon: state.home.lon },
      zoom: state.cfg.map.default_zoom,
      onClick: (lat, lon) => { if (state.pickingHome) setHomeFromMap(lat, lon); },
    });
    DDMap.setHome(state.home.lat, state.home.lon, state.home.label, state.cfg.map.range_rings_m || []);
    showBasemapInfo();
    handleAlertDeepLink();

    buildSettingsNav();
    wireUI();
    connectWS();
    tickClock(); setInterval(tickClock, 1000);
    setInterval(pruneContacts, 3000);
    loadEvents();
  }

  // Opened from a push alert: ?op=lat,lon&drone=id → centre on the operator and
  // open the aircraft detail once it appears.
  function handleAlertDeepLink() {
    const q = new URLSearchParams(location.search);
    const op = q.get("op");
    if (op) {
      const [la, lo] = op.split(",").map(Number);
      if (!Number.isNaN(la) && !Number.isNaN(lo)) {
        DDMap.upsertOperator("_alert", la, lo);
        DDMap.panTo(la, lo);
      }
    }
    const drone = q.get("drone");
    if (drone) {
      let tries = 0;
      const iv = setInterval(() => {
        if (state.contacts.has(drone)) { openDetail(drone); clearInterval(iv); }
        else if (++tries > 12) clearInterval(iv);
      }, 800);
    }
  }

  function applyBrand(brand) {
    if (!brand) return;
    const root = document.documentElement;
    // Feed the config accent into both the concept vars and the map vars.
    if (brand.accent) { root.style.setProperty("--orange", brand.accent); root.style.setProperty("--accent", brand.accent); }
    if (brand.accent) root.style.setProperty("--orange-hot", brand.accent);
    if (brand.accent_alt) root.style.setProperty("--accent-alt", brand.accent_alt);
    if (brand.home) root.style.setProperty("--home", brand.home);
    if (brand.danger) { root.style.setProperty("--danger", brand.danger); }
    if (brand.tagline) $("tagline").textContent = brand.tagline;
    document.title = brand.product_name || "DroneDingo";
  }

  /* ------------------------------ theme ------------------------------ */
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme")
      || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  }
  function setLogoForTheme() {
    const src = currentTheme() === "dark" ? "/vendor/brand/mark-dark.png" : "/vendor/brand/mark.png";
    document.querySelectorAll(".brand-mark, .about-logo").forEach((img) => { img.src = src; });
    const b = $("theme-toggle"); if (b) b.textContent = currentTheme() === "dark" ? "☀" : "☾";
  }
  function initTheme() {
    const saved = localStorage.getItem("dd-theme");
    document.documentElement.setAttribute("data-theme", saved || "dark");
    setLogoForTheme();
  }
  function toggleTheme() {
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("dd-theme", next);
    setLogoForTheme();
    if (window.DDMap) DDMap.setTheme(next);
  }

  /* ------------------------------ websocket ------------------------------ */
  function connectWS() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    state.ws = ws;
    let keepalive = null;
    ws.onopen = () => { setLink(true); keepalive = setInterval(() => ws.readyState === 1 && ws.send("ping"), 20000); };
    ws.onclose = () => { if (keepalive) clearInterval(keepalive); setLink(false); setTimeout(connectWS, 2000); };
    ws.onerror = () => ws.close();
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.kind === "detection" && state.mode === "live") onDetection(msg);
    };
  }
  function setLink(up) {
    $("link-text").textContent = up ? "LIVE" : "OFFLINE";
    $("live-dot").style.background = up ? "#3cdb94" : "var(--danger)";
    $("live-dot").style.boxShadow = up ? "0 0 12px #3cdb94" : "none";
  }

  /* ------------------------------ live detections ------------------------------ */
  function onDetection(d) {
    let c = state.contacts.get(d.drone_id);
    if (!c) { c = { positions: [], lastSeen: 0 }; state.contacts.set(d.drone_id, c); }
    c.last = d; c.lastSeen = Date.now();
    if (d.drone_lat != null) {
      c.positions.push([d.drone_lat, d.drone_lon]);
      if (c.positions.length > 600) c.positions.shift();
      const threat = d.range_m != null && d.range_m <= INNER();
      DDMap.upsertDrone(d.drone_id, d.drone_lat, d.drone_lon, d.heading_deg, threat,
        `${d.model || "Drone"} • ${fmtDist(d.range_m)}`, () => openDetail(d.drone_id));
      DDMap.setTrack(d.drone_id, c.positions);
      if (d.operator_lat != null) DDMap.upsertOperator(d.drone_id, d.operator_lat, d.operator_lon);
    } else if (state.home) {
      // No position fix: we know a drone is out there but not where. Pin a
      // pulsing UFO near Home Base with a small, stable per-contact offset.
      if (!c.unidPos) {
        const ang = Math.random() * Math.PI * 2, r = 0.0012 + Math.random() * 0.0016;
        c.unidPos = [state.home.lat + Math.sin(ang) * r,
                     state.home.lon + Math.cos(ang) * r / Math.cos(state.home.lat * Math.PI / 180)];
      }
      DDMap.upsertUnidentified(d.drone_id, c.unidPos[0], c.unidPos[1],
        "Unidentified contact — no telemetry", () => openDetail(d.drone_id));
    }
    renderContacts();
    refreshAlertStrip();
  }

  function pruneContacts() {
    if (state.mode !== "live") return;
    const now = Date.now();
    for (const [id, c] of state.contacts)
      if (now - c.lastSeen > TTL) { DDMap.removeContact(id); state.contacts.delete(id); }
    renderContacts(); refreshAlertStrip();
  }

  function sortedContacts() {
    // Unidentified (no-telemetry) contacts float to the top — they demand a
    // look precisely because we can't say what or where they are.
    return [...state.contacts.entries()].sort((a, b) => {
      const ua = isUnid(a[1].last), ub = isUnid(b[1].last);
      if (ua !== ub) return ua ? -1 : 1;
      return (a[1].last.range_m ?? 9e9) - (b[1].last.range_m ?? 9e9);
    });
  }

  function renderContacts() {
    const list = $("contact-list"), arr = sortedContacts();
    $("contact-count").textContent = arr.length;
    $("contacts-empty").style.display = arr.length ? "none" : "";
    list.innerHTML = "";
    for (const [id, c] of arr) list.appendChild(contactCard(id, c.last));
    const unid = arr.filter(([, c]) => isUnid(c.last)).length;
    const chip = $("rf-chip");
    if (chip) {
      if (unid) { $("rf-chip-text").textContent = `${unid} unidentified drone${unid > 1 ? "s" : ""} — no Remote ID`; chip.hidden = false; }
      else chip.hidden = true;
    }
  }

  function contactCard(id, d) {
    const el = document.createElement("button");
    el.className = "contact-card"; el.dataset.id = id;
    if (isUnid(d)) {
      el.className = "contact-card unidentified";
      const sig = d.rssi != null ? Math.round(d.rssi) + " dBm" : "signal";
      el.innerHTML =
        `<span class="contact-head"><span class="drone-icon" style="color:var(--danger)">${ICON_UFO}</span>`
        + `<span class="contact-name"><strong>Unidentified drone<span class="unid-tag">No ID</span></strong>`
        + `<small>${esc(d.source || "RF signature")} · identity not broadcast</small></span>`
        + `<span class="rf-chip">${esc(sig)}</span></span>`
        + `<span class="unid-note"><b>Not transmitting Remote ID.</b> Detected by its control-link signature — no serial, operator or precise telemetry. You still know a drone is out there.</span>`;
      el.addEventListener("click", () => openDetail(id));
      return el;
    }
    const opTxt = d.operator_lat != null ? `Operator estimated ${fmtDist(opDist(d))} from base` : "Operator not broadcast";
    el.innerHTML =
      `<span class="contact-head"><span class="drone-icon">${ICON_DRONE}</span>`
      + `<span class="contact-name"><strong>${esc(d.model || "Unknown UA")}</strong>`
      + `<small>${esc(d.source || "")} · ${esc(d.drone_id)}</small></span>`
      + `<span class="contact-distance">${fmtDist(d.range_m)}</span></span>`
      + `<span class="telemetry">`
      + tel("Range", d.compass || "—") + tel("Height", num(d.height_agl_m, " m"))
      + tel("Speed", num(d.speed_mps, " m/s")) + tel("Heading", num(d.heading_deg, "°"))
      + tel("V-Speed", num(d.vspeed_mps, " m/s")) + tel("Signal", d.rssi != null ? Math.round(d.rssi) + " dBm" : "—")
      + `</span>`
      + `<span class="operator-line"><span class="operator-icon">${ICON_OP}</span>${esc(opTxt)}</span>`;
    el.addEventListener("click", () => openDetail(id));
    return el;
  }
  const tel = (k, v) => `<span><small>${k}</small>${esc(v)}</span>`;

  function opDist(d) {
    if (d.operator_lat == null || !state.home) return null;
    return haversine(state.home.lat, state.home.lon, d.operator_lat, d.operator_lon);
  }

  function refreshAlertStrip() {
    const strip = $("alert-strip");
    const threat = sortedContacts().find(([, c]) => c.last.range_m != null && c.last.range_m <= INNER());
    if (!threat) { strip.hidden = true; return; }
    const d = threat[1].last;
    $("alert-text").innerHTML = `<strong>${esc(d.model || "Drone")}</strong> within ${fmtDist(d.range_m)} of `
      + `${esc(state.home.label || "Home Base")} — bearing ${esc(d.compass || d.bearing_deg + "°")}`;
    strip.hidden = false;
  }

  /* ------------------------------ detail modal ------------------------------ */
  function openDetail(id) {
    const c = state.contacts.get(id) || (state.review && state.review.contacts.get(id));
    const d = c && (c.last || c.rows?.[c.rows.length - 1]); if (!d) return;
    $("detail-name").textContent = d.model || "Unknown UA";
    $("detail-id").textContent = `${d.source || ""} · ${d.drone_id}`;
    $("detail-distance").textContent = fmtDist(d.range_m);
    $("detail-icon").innerHTML = ICON_DRONE;
    const rows = [
      ["Serial number", d.drone_id],
      ["Model", d.model || "—"],
      ["Broadcast source", d.source || "—"],
      ["Operator location", d.operator_lat != null ? `${d.operator_lat.toFixed(5)}, ${d.operator_lon.toFixed(5)}` : "not broadcast"],
      ["Operator range", d.operator_lat != null ? fmtDist(opDist(d)) : "—"],
      ["Current range", `${fmtDist(d.range_m)} ${d.compass || ""}`.trim()],
      ["Height (AGL)", num(d.height_agl_m, " m")],
      ["Altitude (MSL)", num(d.alt_msl_m, " m")],
      ["Speed", num(d.speed_mps, " m/s")],
      ["Heading", num(d.heading_deg, "°")],
      ["Signal", d.rssi != null ? Math.round(d.rssi) + " dBm" : "—"],
      ["Node", d.node_id || state.node],
    ];
    $("detail-grid").innerHTML = rows.map(([k, v]) =>
      `<span class="detail-item"><small>${esc(k)}</small><strong>${esc(v)}</strong></span>`).join("");
    openModal("detail-modal");
  }

  /* ------------------------------ sighting log ------------------------------ */
  async function loadEvents() {
    try {
      const r = await (await fetch("/api/events?days=30")).json();
      state.events = r.events || [];
    } catch (_) { state.events = []; }
  }
  const clockOf = (ts) => new Date(ts * 1000).toLocaleString("en-AU",
    { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
  const durOf = (a, b) => {
    let s = Math.max(0, Math.round(b - a)); const h = Math.floor(s / 3600); s -= h * 3600;
    const m = Math.floor(s / 60); s -= m * 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  };
  function renderSightings() {
    const size = 6, ev = state.events, start = state.page * size, end = Math.min(start + size, ev.length);
    $("sighting-rows").innerHTML = ev.slice(start, end).map((s) =>
      `<tr><td><strong>${esc(s.model || "Unknown")}</strong><br><small>${esc(s.drone_id)}</small></td>`
      + `<td>${esc(clockOf(s.first_seen))}</td><td>${durOf(s.first_seen, s.last_seen)}</td>`
      + `<td>${num(s.max_alt_m, " m")}</td><td>${(s.count || 0).toLocaleString()}</td></tr>`).join("")
      || `<tr><td colspan="5" style="color:var(--muted)">No sightings recorded yet.</td></tr>`;
    $("page-caption").textContent = ev.length
      ? `Showing ${start + 1}–${end} of ${ev.length} sightings` : "No sightings yet";
    $("page-prev").disabled = state.page === 0;
    $("page-next").disabled = end >= ev.length;
  }

  /* ------------------------------ home / map pick ------------------------------ */
  function setHomeFromMap(lat, lon) {
    state.pickingHome = false;
    openModal("settings-modal"); renderSettings("Location");
    setTimeout(() => { $("set-lat").value = lat.toFixed(5); $("set-lon").value = lon.toFixed(5); }, 30);
  }
  async function saveHome() {
    const lat = parseFloat($("set-lat").value), lon = parseFloat($("set-lon").value);
    if (Number.isNaN(lat) || Number.isNaN(lon)) return;
    const label = $("set-label").value.trim() || "Home Base";
    const res = await (await fetch("/api/home", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat, lon, label }),
    })).json();
    state.home = { ...state.home, ...res.home }; state.cfg.site.home = state.home;
    DDMap.setHome(lat, lon, label, state.cfg.map.range_rings_m || []); DDMap.panTo(lat, lon);
    setNote("set-note", "Home location saved.", true);
  }

  async function showBasemapInfo() {
    const el = $("basemap-info"); if (!el) return;   // legend kept clean; info lives elsewhere
    try {
      const i = await (await fetch("/api/map/info")).json();
      el.textContent = i.offline ? `Offline · ${i.vector ? "vector" : "raster"}` : "Online basemap";
      el.classList.toggle("offline-ok", !!i.offline);
    } catch (_) {}
  }

  /* ============================ SETTINGS ============================ */
  const SECTIONS = ["Location", "Alerts", "System", "Network", "Updates", "Account", "About"];
  function buildSettingsNav() {
    const nav = $("settings-nav"); nav.innerHTML = "";
    SECTIONS.forEach((name, i) => {
      const b = document.createElement("button");
      b.textContent = name; b.className = i === 0 ? "active" : "";
      b.addEventListener("click", () => {
        nav.querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
        renderSettings(name);
      });
      nav.append(b);
    });
  }
  const setNote = (id, msg, ok) => { const e = $(id); if (e) { e.textContent = msg; e.className = "status-note " + (ok ? "ok" : "bad"); } };
  const field = (label, id, val = "", type = "text", ph = "") =>
    `<label class="field">${label}<input id="${id}" type="${type}" value="${esc(val)}" placeholder="${esc(ph)}"></label>`;

  function renderSettings(name) {
    const c = $("settings-content");
    if (name === "Location") {
      c.innerHTML = `<p>Range and bearing to every contact are measured from the receiver location. Click the map to drop the marker, or type coordinates.</p>`
        + field("Label", "set-label", state.home.label || "Home Base")
        + `<div class="form-grid">${field("Latitude", "set-lat", Number(state.home.lat).toFixed(5))}${field("Longitude", "set-lon", Number(state.home.lon).toFixed(5))}</div>`
        + `<div class="form-actions"><button id="set-pick">Pick on map</button><button class="primary" id="set-save">Save location</button></div><p id="set-note" class="status-note"></p>`;
      $("set-save").onclick = saveHome;
      $("set-pick").onclick = () => { state.pickingHome = true; closeModals(); };
    }
    else if (name === "Alerts") renderAlerts(c);
    else if (name === "System") renderSystem(c);
    else if (name === "Network") renderNetwork(c);
    else if (name === "Updates") renderUpdates(c);
    else if (name === "Account") renderAccount(c);
    else if (name === "About") renderAbout(c);
  }

  async function renderAlerts(c) {
    c.innerHTML = `<p>Phone alerts fire when a drone comes within the alert range of Home Base.</p>
      <h3>DroneDingo Push</h3>
      <p style="color:var(--muted);font-size:13px">Proprietary, end-to-end encrypted alerts sent straight from this appliance — no third-party app, no Apple/Google account. <b id="push-count" style="color:var(--text)"></b></p>
      <div id="push-devices" style="margin:8px 0"></div>
      <div id="push-qr-wrap" hidden style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:10px 0">
        <div id="push-qr" style="width:150px;height:150px;background:#fff;border-radius:12px;padding:8px"></div>
        <div style="min-width:180px;color:var(--muted);font-size:13px">On the phone: scan with the camera, open the link, tap <b>Enable alerts</b>. Link valid ~15 min.<br><span id="push-url" style="color:var(--text);word-break:break-all;font-size:11px"></span></div>
      </div>
      <div class="form-actions"><button id="push-add">Add a phone</button><button id="push-test">Send test push</button></div>
      <p id="push-note" class="status-note"></p>
      <hr style="border:0;border-top:1px solid var(--line);margin:22px 0 16px">
      <h3>Alert behaviour</h3>`
      + `<div class="form-grid">${field("Alert range (m)", "al-ring", "", "number")}${field("Re-alert after (s)", "al-resight", "", "number")}</div>`
      + `<div class="form-grid">${field("Quiet hours", "al-quiet", "", "text", "22:00-06:00")}<label class="check-field"><input type="checkbox" id="al-suppress"> Silence during quiet hours</label></div>`
      + field("Webhook URL (optional)", "al-webhook", "", "text", "https://…")
      + `<div class="form-actions"><button class="primary" id="al-save">Save</button></div><p id="al-note" class="status-note"></p>`;
    try {
      const a = await (await fetch("/api/alerts/config")).json();
      $("al-webhook").value = a.webhook_url || ""; $("al-ring").value = a.alert_ring_m ?? "";
      $("al-resight").value = a.resight_after_s ?? ""; $("al-quiet").value = a.quiet_hours || "";
      $("al-suppress").checked = !!a.quiet_hours_suppress;
    } catch (_) {}
    $("al-save").onclick = async () => {
      await fetch("/api/alerts/config", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          webhook_url: $("al-webhook").value.trim(), alert_ring_m: $("al-ring").value,
          resight_after_s: $("al-resight").value, quiet_hours: $("al-quiet").value.trim(),
          quiet_hours_suppress: $("al-suppress").checked }) });
      setNote("al-note", "Saved.", true);
    };

    // --- DroneDingo Push (registered devices + de-register) ---
    let pushStatus = { devices: 0, public_url: null };
    async function loadDevices() {
      try {
        pushStatus = await (await fetch("/api/push/status")).json();
        $("push-count").textContent = pushStatus.devices
          ? `${pushStatus.devices} device(s) registered.` : "No devices registered yet.";
        const d = await (await fetch("/api/push/devices")).json();
        $("push-devices").innerHTML = (d.devices || []).map((dev) =>
          `<div class="net-row"><span><strong>${esc(dev.label)}</strong> <span class="meta">registered ${dev.added ? new Date(dev.added * 1000).toLocaleDateString() : "—"}</span></span>`
          + `<button data-ep="${esc(dev.endpoint)}" style="padding:6px 12px;border:1px solid var(--line);border-radius:8px;background:var(--surface-soft);color:var(--danger);cursor:pointer">Remove</button></div>`).join("");
        $("push-devices").querySelectorAll("button[data-ep]").forEach((b) => b.onclick = async () => {
          if (!confirm("Remove this device? It will stop receiving alerts.")) return;
          await fetch("/api/push/remove", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ endpoint: b.dataset.ep }) });
          loadDevices();
        });
      } catch (_) {}
    }
    loadDevices();
    $("push-add").onclick = async () => {
      try {
        const { token } = await (await fetch("/api/push/reg-token", { method: "POST" })).json();
        let url, base;
        if (pushStatus.public_url) {
          base = pushStatus.public_url.replace(/\/$/, "");
          url = `${base}/?node=${encodeURIComponent(pushStatus.node)}&t=${token}&k=${pushStatus.pubkey}`;
        } else {
          base = location.origin;
          url = `${base}/push?t=${token}`;
        }
        $("push-url").textContent = url;
        if (window.DDQR) $("push-qr").innerHTML = window.DDQR.svg(url, 134);
        $("push-qr-wrap").hidden = false;
        if (!/^https:/.test(base) && !/^http:\/\/localhost/.test(base))
          setNote("push-note", "This appliance can't reach the registration service — check its internet connection.", false);
        else if (pushStatus.relay_ready === false)
          setNote("push-note", "Registration will open, but this appliance isn't fully provisioned to receive devices yet.", false);
      } catch (_) { setNote("push-note", "Could not create a registration link.", false); }
    };
    $("push-test").onclick = async () => {
      setNote("push-note", "Sending…", true);
      const r = await (await fetch("/api/push/test", { method: "POST" })).json();
      setNote("push-note", r.message || (r.ok ? `Sent to ${r.sent} device(s).` : "No devices registered."), r.ok);
      loadDevices();
    };
  }

  async function renderSystem(c) {
    c.innerHTML = `<div id="sys-body"><p style="color:var(--muted)">Loading…</p></div>
      <div class="form-actions"><button id="sys-refresh">Refresh</button><button id="sys-reboot">Reboot</button></div>
      <p id="sys-note" class="status-note"></p>
      <hr style="border:0;border-top:1px solid var(--line);margin:22px 0 16px">
      <h3>Demo mode</h3>
      <p style="color:var(--muted);font-size:13px">Generate synthetic drone traffic — including an unidentified contact — to explore the console and test alerts &amp; push notifications without radios attached. Off by default on real installs.</p>
      <label class="check-field"><input type="checkbox" id="demo-toggle"> Enable demo traffic</label>
      <p id="demo-note" class="status-note"></p>`;
    const load = async () => {
      const s = await (await fetch("/api/system/status")).json();
      const bar = (label, pct, val) => `<div class="health-row"><strong>${label}</strong><progress value="${Math.round(pct || 0)}" max="100"></progress><span>${val}</span></div>`;
      const t = s.throttle;
      let thr = "";
      if (t) thr = t.healthy
        ? `<div class="throttle-note ok">Power &amp; thermal healthy — no throttling.</div>`
        : `<div class="throttle-note warn">${[...t.active_now.map(x => "<b>" + esc(x) + "</b>"), ...t.since_boot.map(esc)].join("<br>")}</div>`;
      const memPct = s.memory && s.memory.total ? s.memory.percent : 0;
      const loadPct = s.load && s.cpu_count ? (s.load[0] / s.cpu_count) * 100 : 0;
      $("sys-body").innerHTML =
        `<div class="about-stats" style="margin-bottom:14px"><span><small>Host</small><strong>${esc(s.hostname || "—")}</strong></span>`
        + `<span><small>Model</small><strong title="${esc(s.pi_model || "")}">${esc(state.cfg?.brand?.model || "DroneDingo")}</strong></span>`
        + `<span><small>Service</small><strong>${esc(s.service || "—")}</strong></span></div>` + thr
        + bar("Memory", memPct, s.memory && s.memory.total ? memPct + "%" : "—")
        + bar("CPU load", loadPct, s.load ? s.load[0] : "—")
        + bar("CPU temp", (s.cpu_temp_c || 0) / 85 * 100, s.cpu_temp_c != null ? s.cpu_temp_c + "°C" : "—")
        + bar("Disk", s.disk ? s.disk.percent : 0, s.disk ? s.disk.percent + "%" : "—");
    };
    load().catch(() => {});
    $("sys-refresh").onclick = load;
    $("sys-reboot").onclick = async () => {
      if (!confirm("Reboot the appliance now? Detection stops for ~1 minute.")) return;
      await fetch("/api/system/reboot", { method: "POST" }); setNote("sys-note", "Rebooting…", true);
    };
    // Demo mode
    try { $("demo-toggle").checked = !!(await (await fetch("/api/demo")).json()).enabled; } catch (_) {}
    $("demo-toggle").onchange = async (e) => {
      const on = e.target.checked;
      setNote("demo-note", on ? "Starting demo traffic…" : "Stopping demo traffic…", true);
      const r = await (await fetch("/api/demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: on }) })).json();
      e.target.checked = !!r.enabled;
      setNote("demo-note", r.enabled ? "Demo traffic on — synthetic contacts will appear." : "Demo traffic off.", true);
    };
  }

  async function renderNetwork(c) {
    c.innerHTML = `<h3>Interfaces</h3><div id="net-ifaces"><p style="color:var(--muted)">Loading…</p></div>
      <h3>Ethernet</h3>
      <div class="form-grid"><label class="field">Interface<select id="eth-if"></select></label>
      <label class="field">Addressing<select id="eth-mode"><option value="dhcp">Automatic (DHCP)</option><option value="static">Static IP</option></select></label></div>
      <div id="eth-static" hidden>${field("IP / prefix", "eth-ip", "", "text", "192.168.1.50/24")}<div class="form-grid">${field("Gateway", "eth-gw", "", "text", "192.168.1.1")}${field("DNS", "eth-dns", "", "text", "1.1.1.1")}</div></div>
      <div class="form-actions"><button class="primary" id="eth-apply">Apply ethernet</button></div>
      <h3>Wi-Fi</h3><p id="wifi-cur" style="color:var(--muted)">—</p><div id="wifi-list"></div>
      <div class="form-actions"><button id="wifi-scan">Scan networks</button></div>
      <p id="net-note" class="status-note"></p>`;
    $("eth-mode").onchange = () => { $("eth-static").hidden = $("eth-mode").value !== "static"; };
    const loadNet = async () => {
      const n = await (await fetch("/api/system/network")).json();
      const box = $("net-ifaces"), sel = $("eth-if"); box.innerHTML = ""; sel.innerHTML = "";
      (n.interfaces || []).forEach((itf) => {
        box.insertAdjacentHTML("beforeend", `<div class="net-row"><span><strong>${esc(itf.name)}</strong> <span class="meta">${esc(itf.type)} · ${esc(itf.state)}</span></span><span class="meta">${esc((itf.addresses || []).join(", ") || "—")}</span></div>`);
        if (itf.type === "ethernet") sel.insertAdjacentHTML("beforeend", `<option>${esc(itf.name)}</option>`);
      });
      if (!sel.children.length) sel.innerHTML = "<option value=''>No ethernet</option>";
      if (!n.interfaces || !n.interfaces.length) box.innerHTML = '<p style="color:var(--muted)">No interfaces reported (Linux only).</p>';
      $("wifi-cur").textContent = n.wifi ? `Connected: ${n.wifi.name}` : "Not connected to Wi-Fi.";
    };
    loadNet().catch(() => {});
    $("wifi-scan").onclick = async () => {
      const list = $("wifi-list"); list.innerHTML = '<p style="color:var(--muted)">Scanning…</p>';
      const r = await (await fetch("/api/system/wifi/scan")).json();
      list.innerHTML = "";
      (r.networks || []).forEach((net) => {
        const row = document.createElement("div"); row.className = "net-row";
        row.innerHTML = `<span><strong>${esc(net.ssid)}</strong> <span class="meta">${esc(net.security)}</span></span><span class="meta">${net.signal}%</span>`;
        const b = document.createElement("button"); b.textContent = net.active ? "Connected" : "Join"; b.disabled = net.active;
        b.onclick = async () => {
          const pw = net.security && net.security !== "Open" ? prompt(`Password for ${net.ssid}`) : "";
          if (pw === null) return;
          setNote("net-note", "Connecting…", true);
          const res = await (await fetch("/api/system/wifi/connect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ssid: net.ssid, password: pw }) })).json();
          setNote("net-note", res.message || (res.ok ? "Connected." : "Failed."), res.ok); if (res.ok) loadNet();
        };
        row.appendChild(b); list.appendChild(row);
      });
      if (!list.children.length) list.innerHTML = '<p style="color:var(--muted)">No networks found.</p>';
    };
    $("eth-apply").onclick = async () => {
      setNote("net-note", "Applying…", true);
      const res = await (await fetch("/api/system/ethernet", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ iface: $("eth-if").value, mode: $("eth-mode").value, ip: $("eth-ip")?.value || "", gateway: $("eth-gw")?.value || "", dns: $("eth-dns")?.value || "" }) })).json();
      setNote("net-note", res.message || (res.ok ? "Applied." : "Failed."), res.ok); if (res.ok) loadNet();
    };
  }

  function renderUpdates(c) {
    c.innerHTML = `<h3>DroneDingo software</h3><p id="dd-upd" style="color:var(--muted)">Checking…</p>
      <div class="form-actions"><button id="dd-check">Check now</button><button class="primary" id="dd-install" hidden>Install update</button></div><pre class="update-log" id="dd-log" hidden></pre>
      <h3>Firmware</h3><p style="color:var(--muted)">Device firmware is applied through the system package manager.</p>
      <p id="os-upd" style="color:var(--muted)">Not checked.</p>
      <progress id="os-bar" class="apt-bar" hidden></progress>
      <div class="form-actions"><button id="os-check">Check firmware updates</button><button class="primary" id="os-install" hidden>Install firmware updates</button></div>
      <pre class="update-log" id="os-log" hidden></pre>`;
    const ddCheck = async () => {
      $("dd-upd").textContent = "Checking…"; $("dd-install").hidden = true;
      const u = await (await fetch("/api/update/check")).json();
      $("dd-upd").textContent = u.message + (u.build ? `  (build ${u.build})` : "");
      $("dd-upd").className = u.available ? "ok" : ""; $("dd-upd").style.color = u.available ? "" : "var(--muted)";
      if (u.notes) { $("dd-log").hidden = false; $("dd-log").textContent = u.notes; }
      $("dd-install").hidden = !u.available;
    };
    ddCheck().catch(() => {});
    $("dd-check").onclick = ddCheck;
    $("dd-install").onclick = async () => {
      if (!confirm("Install the update and restart DroneDingo now?")) return;
      $("dd-upd").textContent = "Installing… the service will restart.";
      try { const r = await (await fetch("/api/update/install", { method: "POST" })).json(); $("dd-log").hidden = false; $("dd-log").textContent = r.output || r.message; $("dd-upd").textContent = r.message; }
      catch (_) { $("dd-upd").textContent = "Reconnecting after restart…"; setTimeout(() => location.reload(), 8000); }
    };
    $("os-check").onclick = async () => {
      $("os-upd").textContent = "Checking for firmware updates…"; $("os-install").hidden = true;
      $("os-bar").hidden = false; $("os-bar").removeAttribute("value");   // indeterminate
      try {
        const r = await (await fetch("/api/update/os/check")).json();
        $("os-upd").textContent = r.message; $("os-install").hidden = !r.upgradable;
      } finally { $("os-bar").hidden = true; }
    };
    $("os-install").onclick = async () => {
      if (!confirm("Install firmware updates now? This can take several minutes and the appliance may restart.")) return;
      $("os-upd").textContent = "Installing firmware… do not power off.";
      $("os-log").hidden = true;
      $("os-bar").hidden = false; $("os-bar").removeAttribute("value");   // animated during apt
      try {
        const r = await (await fetch("/api/update/os/install", { method: "POST" })).json();
        $("os-upd").textContent = r.message;
        if (r.output) { $("os-log").hidden = false; $("os-log").textContent = r.output; }
      } catch (_) {
        $("os-upd").textContent = "Firmware update interrupted — the appliance may be restarting.";
      } finally { $("os-bar").hidden = true; }
    };
  }

  async function renderAccount(c) {
    const who = await fetch("/api/auth/whoami").then(r => r.json()).catch(() => ({}));
    c.innerHTML = `<p>Signed in as <strong>${esc(who.email || "—")}</strong></p>
      <h3>Change email</h3><div class="form-grid">${field("New email", "ac-email", "", "email", "you@example.com")}${field("Confirm with password", "ac-emailpw", "", "password")}</div>
      <div class="form-actions"><button class="primary" id="ac-email-save">Update email</button></div><p id="ac-email-note" class="status-note"></p>
      <h3>Change password</h3><div class="form-grid">${field("Current password", "ac-cur", "", "password")}${field("New password", "ac-new", "", "password")}</div>
      <div class="form-actions"><button class="primary" id="ac-pw-save">Update password</button></div><p id="ac-pw-note" class="status-note"></p>
      <div style="margin-top:18px"><button id="ac-logout">Sign out</button></div>`;
    $("ac-email-save").onclick = async () => {
      const r = await (await fetch("/api/auth/email", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: $("ac-email").value, password: $("ac-emailpw").value }) })).json();
      setNote("ac-email-note", r.ok ? "Email updated." : (r.error || "Failed."), r.ok);
    };
    $("ac-pw-save").onclick = async () => {
      const r = await (await fetch("/api/auth/password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current: $("ac-cur").value, new: $("ac-new").value }) })).json();
      setNote("ac-pw-note", r.ok ? "Password updated." : (r.error || "Failed."), r.ok);
    };
    $("ac-logout").onclick = async () => { await fetch("/api/auth/logout", { method: "POST" }); location.href = "/login"; };
  }

  async function renderAbout(c) {
    const a = await (await fetch("/api/about")).json();
    c.innerHTML = `<div class="about-brand"><img class="about-logo" style="height:56px;width:auto" src="/vendor/brand/mark.png" alt=""><span><strong>Drone<span>Dingo</span></strong><small>${esc(a.brand.tagline || "")}</small></span></div>
      <div class="about-stats"><span><small>Version</small><strong>${esc(a.version.version)}</strong></span><span><small>Build</small><strong>${esc(a.version.build || a.version.channel)}</strong></span><span><small>Node</small><strong>${esc(a.node_id)}</strong></span></div>
      <p style="color:var(--muted);margin-top:16px">${esc(a.brand.copyright || "")}</p>`;
    setLogoForTheme();
  }

  /* ------------------------------ modals ------------------------------ */
  const layer = () => $("modal-layer");
  const modals = () => [...document.querySelectorAll(".modal")];
  function openModal(id) { layer().hidden = false; modals().forEach(m => m.hidden = m.id !== id); }
  function closeModals() { layer().hidden = true; modals().forEach(m => m.hidden = true); }

  /* ------------------------------ review / playback ------------------------------ */
  async function enterReview() {
    state.mode = "review"; $("mode-live").classList.remove("active"); $("mode-review").classList.add("active");
    $("pb").hidden = false;
    for (const id of state.contacts.keys()) DDMap.removeContact(id);
    state.contacts.clear(); renderContacts(); $("alert-strip").hidden = true;
    await loadReviewWindow();
  }
  function enterLive() {
    state.mode = "live"; $("mode-live").classList.add("active"); $("mode-review").classList.remove("active");
    $("pb").hidden = true; stopPlay();
    if (state.review) { DDMap.clearContacts(); state.review = null; }
    renderContacts();
  }
  async function loadReviewWindow() {
    const win = parseInt($("pb-window").value, 10);
    const end = Date.now() / 1000, start = end - win;
    const r = await (await fetch(`/api/detections?start=${start}&end=${end}`)).json();
    const rows = r.detections || [];
    const contacts = new Map();
    for (const d of rows) {
      if (!contacts.has(d.drone_id)) contacts.set(d.drone_id, { rows: [], model: d.model });
      contacts.get(d.drone_id).rows.push(d);
    }
    DDMap.clearContacts();
    state.review = { start, end, contacts, playhead: start, playing: false };
    renderReviewAt(start);
  }
  function renderReviewAt(t) {
    if (!state.review) return;
    for (const [id, c] of state.review.contacts) {
      const upto = c.rows.filter(r => r.ts <= t);
      DDMap.setTrack(id, upto.filter(r => r.drone_lat != null).map(r => [r.drone_lat, r.drone_lon]));
      const last = upto[upto.length - 1];
      if (last && (t - last.ts) < 20 && last.drone_lat != null) {
        DDMap.upsertDrone(id, last.drone_lat, last.drone_lon, last.heading_deg, false, `${c.model || "Drone"}`, () => openDetail(id));
        if (last.operator_lat != null) DDMap.upsertOperator(id, last.operator_lat, last.operator_lon);
      } else DDMap.hideMarkers(id);
    }
    const frac = (t - state.review.start) / (state.review.end - state.review.start);
    $("pb-scrub").value = Math.round(frac * 1000);
    $("pb-time").textContent = new Date(t * 1000).toLocaleTimeString("en-AU", { hour12: false });
  }
  let playTimer = null;
  function togglePlay() { state.review && (state.review.playing ? stopPlay() : startPlay()); }
  function startPlay() {
    if (!state.review) return; state.review.playing = true; $("pb-play").textContent = "⏸";
    const speed = parseInt($("pb-speed").value, 10);
    playTimer = setInterval(() => {
      if (!state.review) return stopPlay();
      state.review.playhead += speed;
      if (state.review.playhead >= state.review.end) { state.review.playhead = state.review.end; renderReviewAt(state.review.playhead); return stopPlay(); }
      renderReviewAt(state.review.playhead);
    }, 250);
  }
  function stopPlay() { if (playTimer) clearInterval(playTimer); playTimer = null; if (state.review) state.review.playing = false; const p = $("pb-play"); if (p) p.textContent = "▶"; }

  /* ------------------------------ wiring ------------------------------ */
  function wireUI() {
    $("settings-open").onclick = () => { openModal("settings-modal"); renderSettings("Location"); };
    $("sightings-open").onclick = () => { state.page = 0; renderSightings(); openModal("sightings-modal"); };
    $("theme-toggle").onclick = toggleTheme;
    document.querySelectorAll(".close-modal").forEach(b => b.addEventListener("click", closeModals));
    layer().addEventListener("click", (e) => { if (e.target === layer()) closeModals(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModals(); });
    $("detail-history").onclick = () => { state.page = 0; renderSightings(); openModal("sightings-modal"); };
    $("page-prev").onclick = () => { state.page--; renderSightings(); };
    $("page-next").onclick = () => { state.page++; renderSightings(); };
    $("mode-live").onclick = enterLive;
    $("mode-review").onclick = enterReview;
    $("pb-play").onclick = togglePlay;
    $("pb-window").onchange = loadReviewWindow;
    $("pb-scrub").oninput = (e) => {
      if (!state.review) return; stopPlay();
      state.review.playhead = state.review.start + (e.target.value / 1000) * (state.review.end - state.review.start);
      renderReviewAt(state.review.playhead);
    };
  }

  /* ------------------------------ clock / geo ------------------------------ */
  function tickClock() {
    const now = new Date();
    $("clock").textContent = now.toLocaleTimeString("en-AU", { hour12: false });
    $("current-date").textContent = now.toLocaleDateString("en-AU", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
  }
  const R = 6371000, rad = (d) => d * Math.PI / 180;
  function haversine(a, b, c, d) {
    const dφ = rad(c - a), dλ = rad(d - b);
    const s = Math.sin(dφ / 2) ** 2 + Math.cos(rad(a)) * Math.cos(rad(c)) * Math.sin(dλ / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(s));
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
