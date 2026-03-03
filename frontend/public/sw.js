// Hook Observatory Service Worker
// 快取策略：靜態資源 cache-first，HTML network-first，API 不快取

const CACHE_NAME = "hook-observatory-v1";

// ── Web Push ──
self.addEventListener("push", (event) => {
  if (!event.data) return;
  const data = event.data.json();
  event.waitUntil(
    self.registration.showNotification(data.title || "Hook Observatory", {
      body: data.body || "",
      icon: data.icon || "/apps/hook/icon-192.svg",
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

// 需預快取的靜態資源（build 時帶 hash，內容不變）
const PRECACHE_URLS = [
  "./",
];

// ── Install：預快取核心資源 ──
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  // 跳過等待，新 SW 立即接管
  self.skipWaiting();
});

// ── Activate：清除舊版快取 ──
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names
          .filter((name) => name.startsWith("hook-observatory-") && name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      )
    )
  );
  // 立即控制所有已開啟的頁面
  self.clients.claim();
});

// ── Fetch：依請求類型選擇策略 ──
self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // 只處理同源請求
  if (url.origin !== self.location.origin) return;

  // API 路徑 — 永遠走網路，不快取
  if (url.pathname.includes("/api/")) return;

  // 靜態資源（帶 hash 的 JS/CSS）— cache-first
  // Vite 產出的檔名含 hash（如 index-HjOzykZz.js），內容不變可安全快取
  if (url.pathname.match(/\/assets\/.*\.[a-f0-9]{8,}\.(js|css)$/)) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // SVG 圖示等靜態資源 — cache-first
  if (url.pathname.match(/\.(svg|png|ico|woff2?)$/)) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // HTML 及其他 — network-first，網路失敗時回退快取
  if (request.mode === "navigate" || request.headers.get("accept")?.includes("text/html")) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => caches.match(request).then((cached) => cached || caches.match("./")))
    );
    return;
  }
});
