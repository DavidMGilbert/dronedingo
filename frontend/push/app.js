/* DroneDingo Push — device registration (runs on the phone from the QR). */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const token = params.get("t") || params.get("token") || "";

  function setStatus(msg, cls) { const s = $("status"); s.textContent = msg; s.className = "status " + (cls || ""); }
  function b64ToU8(b64) {
    const pad = "=".repeat((4 - (b64.length % 4)) % 4);
    const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
  }

  const secure = window.isSecureContext;
  const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

  if (!secure) {
    setStatus("This page must be opened over HTTPS to enable alerts.", "bad");
    $("hint").textContent = "Open the appliance over its https:// address (or the DroneDingo alerts site) and scan the QR again.";
    $("enable").disabled = true;
  } else if (!supported) {
    setStatus("This browser can't do push notifications.", "bad");
    $("hint").textContent = "On iPhone: tap Share → Add to Home Screen, open it from there, then enable alerts (iOS 16.4+).";
    $("enable").disabled = true;
  }

  async function enable() {
    $("enable").disabled = true; setStatus("Setting up…");
    try {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") { setStatus("Notifications were not allowed.", "bad"); $("enable").disabled = false; return; }

      const reg = await navigator.serviceWorker.register("/push/sw.js", { scope: "/push/" });
      await navigator.serviceWorker.ready;

      const { key } = await (await fetch("/api/push/pubkey")).json();
      let sub = await reg.pushManager.getSubscription();
      if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToU8(key) });

      const j = sub.toJSON();
      const res = await fetch("/api/push/subscribe", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint: j.endpoint, keys: j.keys, token, ua: navigator.userAgent.slice(0, 120) }),
      });
      const d = await res.json();
      if (res.ok && d.ok) {
        setStatus("✓ This phone is now registered for DroneDingo alerts.", "ok");
        $("enable").textContent = "Alerts enabled";
        $("hint").textContent = "You can close this page. Add it to your Home Screen to keep alerts reliable.";
        try { reg.showNotification("DroneDingo", { body: "Alerts enabled on this phone.", icon: "/vendor/brand/icon-192.png" }); } catch (_) {}
      } else {
        setStatus(d.error || "Registration failed.", "bad"); $("enable").disabled = false;
      }
    } catch (e) {
      setStatus("Could not enable alerts: " + e.message, "bad"); $("enable").disabled = false;
    }
  }

  $("enable").addEventListener("click", enable);
})();
