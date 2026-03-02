// Workshop Sentinel Service Worker — runtime cache only
const CACHE_NAME = 'sentinel-v2';

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // API — network only
    if (url.pathname.includes('/api/')) return;

    // Static assets — stale-while-revalidate
    if (url.pathname.match(/\.(css|js|json|svg|png|ico)$/)) {
        event.respondWith(
            caches.open(CACHE_NAME).then(cache =>
                cache.match(event.request).then(cached => {
                    const fetching = fetch(event.request).then(resp => {
                        if (resp.ok) cache.put(event.request, resp.clone());
                        return resp;
                    }).catch(() => cached);
                    return cached || fetching;
                })
            )
        );
        return;
    }

    // HTML — network first
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request))
    );
});
