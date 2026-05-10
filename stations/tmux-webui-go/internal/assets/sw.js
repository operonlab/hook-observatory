const CACHE_NAME = 'tmux-webui-__GIT_HASH__';

// ── Web Push ──
self.addEventListener('push', (event) => {
  if (!event.data) return;
  const data = event.data.json();
  event.waitUntil(
    self.registration.showNotification(data.title || 'Workshop', {
      body: data.body || '',
      icon: data.icon || './icon-192.png',
      tag: data.tag,
      data: { url: data.url || '/apps/tmux/' },
      vibrate: data.severity === 'critical' ? [200, 100, 200, 100, 200] : [100, 50, 100],
      requireInteraction: data.severity !== 'info',
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = event.notification.data?.url || '/apps/tmux/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wc) => {
      for (const c of wc) {
        if ('focus' in c) { c.navigate(url); return c.focus(); }
      }
      return clients.openWindow(url);
    })
  );
});

// Push-Only SW: no cache strategy (iOS Safari SW cache is too buggy for
// operation-heavy apps — stale assets, POST interference, cookie isolation).
// Static assets rely on normal HTTP caching (Cache-Control headers).

self.addEventListener('install', (e) => {
  // Purge any leftover caches from previous SW versions
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.map(k => caches.delete(k))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(self.clients.claim());
});
