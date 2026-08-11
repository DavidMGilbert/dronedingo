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
  let url = "/";
  if (d.operator_lat != null && d.operator_lon != null) {
    url = `https://www.openstreetmap.org/?mlat=${d.operator_lat}&mlon=${d.operator_lon}` +
          `#map=17/${d.operator_lat}/${d.operator_lon}`;
  }
  event.waitUntil(clients.openWindow(url));
});
