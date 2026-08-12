/* DroneDingo Push — device registration (appliance-hosted /push page). */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const token = params.get("t") || params.get("token") || "";

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

  const standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
  const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

  if (!window.isSecureContext) {
    fail("This page must be opened over HTTPS to enable alerts.");
    $("hint").textContent = "Open the appliance over its https:// address (or the DroneDingo alerts site) and scan the QR again.";
    $("enable").disabled = true;
  } else if (!supported) {
    fail("This browser can't do push notifications.");
    $("hint").textContent = isIOS
      ? "On iPhone: Share → Add to Home Screen, open it from there, then enable (iOS 16.4+)."
      : "Open this link in Chrome (not inside another app's browser).";
    $("enable").disabled = true;
  } else if (isIOS && !standalone) {
    $("hint").textContent = "iPhone: tap Share → Add to Home Screen, open DroneDingo from the Home Screen, then Enable.";
  }

  async function enable() {
    $("enable").disabled = true;
    try {
      step("Requesting permission…");
      const perm = await withTimeout(Notification.requestPermission(), 60000, "permission prompt didn't return");
      if (perm !== "granted") { fail("Notifications were not allowed."); return; }

      step("Registering…");
      const reg = await navigator.serviceWorker.register("/push/sw.js", { scope: "/push/" });
      await withTimeout(navigator.serviceWorker.ready, 12000, "the notification service didn't start (reload and retry)");

      step("Subscribing…");
      const { key } = await (await fetch("/api/push/pubkey")).json();
      let sub = await reg.pushManager.getSubscription();
      if (sub) {
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
            : "Couldn't reach the push service. Open in Chrome/Safari (not an in-app browser).");
      }

      step("Saving…");
      const j = sub.toJSON();
      const res = await withTimeout(fetch("/api/push/subscribe", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint: j.endpoint, keys: j.keys, token, ua: navigator.userAgent.slice(0, 120) }),
      }), 15000, "couldn't reach the appliance");
      const d = await res.json();
      if (res.ok && d.ok) {
        setStatus("✓ This phone is now registered for DroneDingo alerts.", "ok");
        $("enable").textContent = "Alerts enabled";
        $("hint").textContent = "You can close this page. Add it to your Home Screen to keep alerts reliable.";
        try { reg.showNotification("DroneDingo", { body: "Alerts enabled on this phone.", icon: "/vendor/brand/icon-192.png" }); } catch (_) {}
      } else { fail(d.error || "Registration failed."); }
    } catch (e) { fail("Could not enable alerts: " + (e.message || e)); }
  }
  $("enable").addEventListener("click", enable);
})();
