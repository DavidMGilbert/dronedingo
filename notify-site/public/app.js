/* DroneDingo Alerts — device registration on notify.dronedingo.com.au.
   Reads the appliance node id, one-time token and the appliance's VAPID public
   key from the QR URL, subscribes this phone with that key, and parks the
   subscription for the appliance to collect. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const p = new URLSearchParams(location.search);
  let node = p.get("node") || "";
  let token = p.get("t") || p.get("token") || "";
  let key = p.get("k") || "";      // appliance VAPID public key (base64url)

  // iOS drops the query string when the PWA is launched from the Home Screen,
  // so stash the registration details on first load and restore them after.
  try {
    if (node && token && key) {
      localStorage.setItem("dd-reg", JSON.stringify({ node, token, key }));
    } else {
      const s = JSON.parse(localStorage.getItem("dd-reg") || "{}");
      node = node || s.node || ""; token = token || s.token || ""; key = key || s.key || "";
    }
  } catch (_) {}

  const setStatus = (m, c) => { const s = $("status"); s.textContent = m; s.className = "status " + (c || ""); };
  const step = (m) => { setStatus(m); console.log("[dronedingo]", m); };
  const fail = (m) => { setStatus(m, "bad"); $("enable").disabled = false; console.error("[dronedingo]", m); };
  const withTimeout = (promise, ms, msg) =>
    Promise.race([promise, new Promise((_, rej) => setTimeout(() => rej(new Error(msg)), ms))]);

  function b64ToU8(b64) {
    const pad = "=".repeat((4 - (b64.length % 4)) % 4);
    const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
  }
  // navigator.serviceWorker.ready can hang forever on iOS; resolve as soon as
  // the worker is active (or after a grace period) and let subscribe() proceed.
  function waitForActive(reg, ms) {
    return new Promise((resolve) => {
      if (reg.active) return resolve(true);
      let done = false;
      const finish = (v) => { if (!done) { done = true; resolve(v); } };
      const t = setTimeout(() => finish(false), ms);
      const sw = reg.installing || reg.waiting;
      if (sw) sw.addEventListener("statechange", () => { if (reg.active) { clearTimeout(t); finish(true); } });
      navigator.serviceWorker.addEventListener("controllerchange", () => { clearTimeout(t); finish(true); }, { once: true });
    });
  }

  // In-app browsers (scanned inside Instagram/Facebook/a QR app) usually can't
  // do Web Push. Standalone = launched from the Home Screen (installed).
  const standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
  const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

  if (!window.isSecureContext) { fail("This page must be served over HTTPS."); $("enable").disabled = true; }
  else if (!node || !token || !key) {
    fail("This link is missing its registration details.");
    $("hint").textContent = "On the appliance: Settings → Alerts → DroneDingo Push → Add a phone, then scan the fresh QR.";
    $("enable").disabled = true;
  } else if (!supported) {
    fail("This browser can't do push notifications.");
    $("hint").textContent = isIOS
      ? "On iPhone: tap Share → Add to Home Screen, then open DroneDingo from the Home Screen (iOS 16.4+)."
      : "Open this link in Chrome (not inside another app's browser).";
    $("enable").disabled = true;
  } else if (isIOS && !standalone) {
    // iOS ONLY does Web Push from an installed PWA — block the Safari-tab attempt.
    fail("On iPhone, add DroneDingo to your Home Screen first.");
    $("hint").textContent = "Tap the Share icon → Add to Home Screen, then open DroneDingo from the Home Screen and tap Enable.";
    $("enable").disabled = true;
  }

  async function enable() {
    $("enable").disabled = true;
    try {
      step("Requesting permission…");
      const perm = await withTimeout(Notification.requestPermission(), 60000, "permission prompt didn't return");
      if (perm !== "granted") { fail("Notifications were not allowed for this site."); return; }

      step("Registering… (v2)");
      const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
      await waitForActive(reg, 8000);        // best-effort; don't fail if slow

      step("Subscribing…");
      let sub = await reg.pushManager.getSubscription();
      if (sub) {
        // Reuse only if it was made with this appliance's key; else replace.
        const existing = new Uint8Array(sub.options.applicationServerKey || []);
        const wanted = b64ToU8(key);
        const same = existing.length === wanted.length && existing.every((b, i) => b === wanted[i]);
        if (!same) { await sub.unsubscribe().catch(() => {}); sub = null; }
      }
      if (!sub) {
        sub = await withTimeout(
          reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToU8(key) }),
          25000,
          isIOS && !standalone
            ? "Add DroneDingo to the Home Screen first, open it from there, then Enable."
            : "Couldn't reach the push service. Open in Chrome/Safari (not an in-app browser) and check the connection.");
      }

      step("Saving…");
      const j = sub.toJSON();
      const res = await withTimeout(fetch("/api/register.php", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node, token, subscription: { endpoint: j.endpoint, keys: j.keys } }),
      }), 15000, "couldn't reach the registration server");
      const d = await res.json();
      if (res.ok && d.ok) {
        setStatus("✓ Registered. Your DroneDingo will confirm shortly.", "ok");
        $("enable").textContent = "Alerts enabled";
        $("hint").textContent = "You can close this page. A confirmation alert arrives within a minute.";
      } else { fail(d.error || "Registration failed on the server."); }
    } catch (e) { fail("Could not enable alerts: " + (e.message || e)); }
  }
  $("enable").addEventListener("click", enable);
})();
