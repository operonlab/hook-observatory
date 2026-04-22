// No-op SW: auto-survey has no Push notifications and no offline requirement.
// Kept as empty SW to cleanly unregister any previously cached data on iOS Safari.

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.map((k) => caches.delete(k))))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});
