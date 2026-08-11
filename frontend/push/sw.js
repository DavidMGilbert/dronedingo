/* DroneDingo Push — service worker. Receives encrypted push and shows the
   alert; tapping it opens the operator's location on a map when available. */
self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let payload = { title: "DroneDingo", body: "Drone detected." };
  try { payload = event.data.json(); } catch (_) {}
  const data = payload.data || {};
  event.waitUntil(self.registration.showNotification(payload.title || "DroneDingo", {
    body: payload.body || "",
    icon: "/vendor/brand/icon-192.png",
    badge: "/vendor/brand/favicon-64.png",
    tag: "dronedingo-alert",
    renotify: true,
    vibrate: [180, 80, 180],
    data,
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const d = event.notification.data || {};
  let url = "/";
  if (d.operator_lat != null && d.operator_lon != null) {
    url = `https://www.openstreetmap.org/?mlat=${d.operator_lat}&mlon=${d.operator_lon}` +
          `#map=17/${d.operator_lat}/${d.operator_lon}`;
  }
  event.waitUntil(clients.openWindow(url));
});
