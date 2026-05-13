// Hook Observatory Service Worker
// 快取策略：靜態資源 cache-first，HTML network-first，API 不快取

const CACHE_NAME = "hook-observatory-v2";

// ── Web Push ──
self.addEventListener("push", (event) => {
  if (!event.data) return;
  const data = event.data.json();
  event.waitUntil(
    self.registration.showNotification(data.title || "Hook Observatory", {
      body: data.body || "",
      icon: data.icon || "/apps/hook/icon-192.png",
      tag: data.tag,
      data: { url: data.url || "/apps/hook/" },
      vibrate: data.severity === "critical" ? [200, 100, 200, 100, 200] : [100, 50, 100],
      requireInteraction: data.severity !== "info",
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/apps/hook/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((wc) => {
      for (const c of wc) {
        if ("focus" in c) { c.navigate(url); return c.focus(); }
      }
      return clients.openWindow(url);
    })
  );
});

// Push-Only: no cache (iOS Safari SW cache causes stale assets & POST interference)
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.map((k) => caches.delete(k))))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});
