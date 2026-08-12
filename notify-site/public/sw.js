/* DroneDingo Alerts — service worker (notify.dronedingo.com.au).
   Receives the appliance's encrypted push and shows it; tapping opens the
   operator's location on a map when present. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let payload = { title: "DroneDingo", body: "Drone detected." };
  try { payload = event.data.json(); } catch (_) {}
  const data = payload.data || {};
  event.waitUntil(self.registration.showNotification(payload.title || "DroneDingo", {
    body: payload.body || "",
    icon: "/icons/icon-192.png",
    badge: "/icons/favicon-64.png",
    tag: "dronedingo-alert",
    renotify: true,
    vibrate: [180, 80, 180],
    data,
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const d = event.notification.data || {};
  // Open the DroneDingo portal (deep-linked to the operator + aircraft) when the
  // appliance provided it; otherwise just open the app root.
  const url = d.url || "/";
  event.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
    for (const w of wins) { if (w.url.startsWith(url.split("?")[0]) && "focus" in w) return w.focus(); }
    return clients.openWindow(url);
  }));
});
