/* DroneDingo Alerts — device registration on notify.dronedingo.com.au.
   Reads the appliance node id, one-time token and the appliance's VAPID public
   key from the QR URL, subscribes this phone with that key, and parks the
   subscription for the appliance to collect. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const p = new URLSearchParams(location.search);
  const node = p.get("node") || "";
  const token = p.get("t") || p.get("token") || "";
  const key = p.get("k") || "";   // appliance VAPID public key (base64url)

  const setStatus = (m, c) => { const s = $("status"); s.textContent = m; s.className = "status " + (c || ""); };
  function b64ToU8(b64) {
    const pad = "=".repeat((4 - (b64.length % 4)) % 4);
    const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
  }

  const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  if (!window.isSecureContext) { setStatus("This page must be served over HTTPS.", "bad"); $("enable").disabled = true; }
  else if (!node || !token || !key) {
    setStatus("This link is missing its registration details.", "bad");
    $("hint").textContent = "Open Settings → Alerts → DroneDingo Push on the appliance and scan the QR again.";
    $("enable").disabled = true;
  } else if (!supported) {
    setStatus("This browser can't do push notifications.", "bad");
    $("hint").textContent = "On iPhone: Share → Add to Home Screen, open it from there, then enable alerts (iOS 16.4+).";
    $("enable").disabled = true;
  }

  async function enable() {
    $("enable").disabled = true; setStatus("Setting up…");
    try {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") { setStatus("Notifications were not allowed.", "bad"); $("enable").disabled = false; return; }

      const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
      await navigator.serviceWorker.ready;

      let sub = await reg.pushManager.getSubscription();
      if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToU8(key) });

      const j = sub.toJSON();
      const res = await fetch("/api/register.php", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node, token, subscription: { endpoint: j.endpoint, keys: j.keys } }),
      });
      const d = await res.json();
      if (res.ok && d.ok) {
        setStatus("✓ Registered. Your DroneDingo will confirm shortly.", "ok");
        $("enable").textContent = "Alerts enabled";
        $("hint").textContent = "You can close this page. Add it to your Home Screen to keep alerts reliable. A test alert will arrive within a minute.";
      } else { setStatus(d.error || "Registration failed.", "bad"); $("enable").disabled = false; }
    } catch (e) { setStatus("Could not enable alerts: " + e.message, "bad"); $("enable").disabled = false; }
  }
  $("enable").addEventListener("click", enable);
})();
