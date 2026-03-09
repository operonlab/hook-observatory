// Cronicle PWA Service Worker — minimal (install-only, no fetch interception)
// Enables PWA install prompt and Add to Home Screen without caching any requests.
// All resources served fresh from network — no stale API data risk.

var CACHE_NAME = 'cronicle-v1';

self.addEventListener('install', function(event) {
  self.skipWaiting();
});

self.addEventListener('activate', function(event) {
  // Clean up any caches from previous versions
  event.waitUntil(
    caches.keys().then(function(cacheNames) {
      return Promise.all(
        cacheNames.map(function(cacheName) {
          return caches.delete(cacheName);
        })
      );
    }).then(function() {
      return self.clients.claim();
    })
  );
});

// No fetch handler — all requests go directly to network.
// This avoids caching API responses (job status, schedule data)
// which must always be fresh.
