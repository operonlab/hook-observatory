// Cronicle PWA Service Worker
var CACHE_NAME = 'cronicle-v1';
var PRECACHE_URLS = [
  './',
  'js/combo.min.js',
  'js/common.min.js',
  'js/codemirror.min.js',
  'js/i18n.js',
  'js/home-worker.js',
  'css/style.css',
  'css/base.css',
  'css/codemirror.css',
  'css/font-awesome.min.css',
  'css/materialdesignicons.min.css',
  'images/loading.gif',
  'favicon.ico'
];

// Install: precache static assets
self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(PRECACHE_URLS);
    }).then(function() {
      return self.skipWaiting();
    })
  );
});

// Activate: clean old caches
self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then(function(cacheNames) {
      return Promise.all(
        cacheNames.filter(function(cacheName) {
          return cacheName !== CACHE_NAME;
        }).map(function(cacheName) {
          return caches.delete(cacheName);
        })
      );
    }).then(function() {
      return self.clients.claim();
    })
  );
});

// Fetch: network-first for API, cache-first for static
self.addEventListener('fetch', function(event) {
  var url = new URL(event.request.url);

  // Skip non-GET requests
  if (event.request.method !== 'GET') return;

  // Skip WebSocket and socket.io requests
  if (url.pathname.indexOf('/socket.io/') !== -1) return;

  // API calls: network-first
  if (url.pathname.indexOf('/api/') === 0) {
    event.respondWith(
      fetch(event.request).catch(function() {
        return caches.match(event.request);
      })
    );
    return;
  }

  // Static assets: cache-first, update in background (stale-while-revalidate)
  event.respondWith(
    caches.match(event.request).then(function(cached) {
      if (cached) {
        // Return cached immediately, refresh in background
        fetch(event.request).then(function(response) {
          if (response && response.status === 200) {
            var responseClone = response.clone();
            caches.open(CACHE_NAME).then(function(cache) {
              cache.put(event.request, responseClone);
            });
          }
        }).catch(function() { /* ignore network errors */ });
        return cached;
      }
      // Not in cache: fetch from network and cache for next time
      return fetch(event.request).then(function(response) {
        if (response && response.status === 200) {
          var responseClone = response.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(event.request, responseClone);
          });
        }
        return response;
      });
    })
  );
});
