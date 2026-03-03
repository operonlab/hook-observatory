const CACHE_NAME = 'tmux-webui-__GIT_HASH__';

// ── Web Push ──
self.addEventListener('push', (event) => {
  if (!event.data) return;
  const data = event.data.json();
  event.waitUntil(
    self.registration.showNotification(data.title || 'Workshop', {
      body: data.body || '',
      icon: data.icon || './icon-192.svg',
      tag: data.tag,
      data: { url: data.url || '/v2/apps/tmux/' },
      vibrate: data.severity === 'critical' ? [200, 100, 200, 100, 200] : [100, 50, 100],
      requireInteraction: data.severity !== 'info',
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = event.notification.data?.url || '/v2/apps/tmux/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wc) => {
      for (const c of wc) {
        if ('focus' in c) { c.navigate(url); return c.focus(); }
      }
      return clients.openWindow(url);
    })
  );
});

const PRECACHE_URLS = [
  './',
  './static/css/main.css',
  './static/js/terminal.js',
  './static/js/metrics.js',
  './static/js/app.js',
  './static/js/keys.js',
  './static/js/autocomplete.js',
  './static/js/gestures.js',
  './icon-192.svg',
  './icon-512.svg',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // Skip: WebSocket, API, non-GET
  if (e.request.method !== 'GET') return;
  if (url.pathname.includes('/api/')) return;
  if (url.pathname.includes('/ws/')) return;

  // HTML (navigation): Network-First
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request)
        .then(res => {
          const clone = res.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
          return res;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // Static assets: Cache-First
  e.respondWith(
    caches.match(e.request, { ignoreSearch: true })
      .then(cached => cached || fetch(e.request).then(res => {
        const clone = res.clone();
        caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
        return res;
      }))
  );
});
