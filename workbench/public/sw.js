const CACHE_NAME = "workshop-__CACHE_VERSION__";
const APP_SHELL = ["/manifest.json", "/icons/icon-192.svg"];

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

// Install: cache app shell (excluding index.html to ensure fresh loads)
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)),
  );
  self.skipWaiting();
});

// Activate: cleanup ALL old caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)),
      ),
    ),
  );
  self.clients.claim();
});

// Fetch strategy:
//   - Auth / health              → network-only
//   - API GET (cacheable list)   → stale-while-revalidate (memvault + intelflow reads)
//   - API (other / mutations)    → network-only
//   - Navigation (HTML)          → network-first (fallback to cache for offline)
//   - Hashed assets (.js/.css)   → cache-first (immutable)
//   - Other static               → stale-while-revalidate
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Pass-through for proxied station apps (hook-observatory, etc.)
  // These are separate apps with their own frontend; SW should not interfere.
  if (url.pathname.startsWith("/apps/")) return;

  // Cache-first for Google Fonts (immutable once loaded)
  if (
    url.hostname === "fonts.googleapis.com" ||
    url.hostname === "fonts.gstatic.com"
  ) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        return cached || fetch(event.request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        });
      }),
    );
    return;
  }

  // Network-only for auth, health, and mutation requests
  if (
    url.pathname.startsWith("/auth") ||
    url.pathname.startsWith("/health")
  ) {
    event.respondWith(
      fetch(event.request).catch(
        () => new Response(JSON.stringify({ error: "offline" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    return;
  }

  // Stale-while-revalidate for cacheable API GET requests
  const CACHEABLE_API_PREFIXES = [
    "/api/memvault/blocks",
    "/api/memvault/profile",
    "/api/memvault/kg/",
    "/api/memvault/skills",
    "/api/memvault/attitudes",
    "/api/intelflow/dashboard",
    "/api/intelflow/reports",
    "/api/intelflow/topics",
    "/api/intelflow/timeline",
  ];
  if (
    url.pathname.startsWith("/api") &&
    event.request.method === "GET" &&
    CACHEABLE_API_PREFIXES.some((p) => url.pathname.startsWith(p))
  ) {
    event.respondWith(
      caches.open(CACHE_NAME).then((cache) =>
        cache.match(event.request).then((cached) => {
          const fetchPromise = fetch(event.request)
            .then((response) => {
              if (response.ok) {
                cache.put(event.request, response.clone());
              }
              return response;
            })
            .catch(
              () => cached || new Response(JSON.stringify({ error: "offline" }), {
                status: 503,
                headers: { "Content-Type": "application/json" },
              }),
            );
          return cached || fetchPromise;
        }),
      ),
    );
    return;
  }

  // Network-only for other API requests (POST/PATCH/DELETE, uncached endpoints)
  if (url.pathname.startsWith("/api")) {
    event.respondWith(
      fetch(event.request).catch(
        () => new Response(JSON.stringify({ error: "offline" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    return;
  }

  // Network-first for navigation requests (HTML pages)
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() => caches.match(event.request)),
    );
    return;
  }

  // Cache-first for content-hashed assets (filename contains 8+ char hash)
  const isHashedAsset = /\.[a-f0-9]{8,}\.(js|css|woff2?|png|svg|jpg|webp)(\?|$)/.test(url.pathname);
  if (isHashedAsset) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        return cached || fetch(event.request).then((response) => {
          if (response.ok && url.origin === self.location.origin) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        });
      }),
    );
    return;
  }

  // Stale-while-revalidate for other static assets
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fetchPromise = fetch(event.request).then((response) => {
        if (response.ok && url.origin === self.location.origin) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      });
      return cached || fetchPromise;
    }),
  );
});
