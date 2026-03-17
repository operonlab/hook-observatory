// Push-Only Service Worker — NO caching.
// Rsbuild content-hashed assets + HTTP Cache-Control headers handle caching.

// ── Web Push ──
self.addEventListener("push", (event) => {
  if (!event.data) return;
  const data = event.data.json();
  event.waitUntil(
    self.registration.showNotification(data.title || "Workshop", {
      body: data.body || "",
      icon: data.icon || "/icons/icon-192.svg",
      tag: data.tag,
      data: { url: data.url || "/" },
      vibrate: data.severity === "critical" ? [200, 100, 200, 100, 200] : [100, 50, 100],
      requireInteraction: data.severity !== "info",
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((wc) => {
      for (const c of wc) {
        if ("focus" in c) { c.navigate(url); return c.focus(); }
      }
      return clients.openWindow(url);
    })
  );
});

self.addEventListener("install", (event) => {
  // Purge ALL caches from any previous SW version
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.map((k) => caches.delete(k)))
    ),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});
