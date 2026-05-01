// system-monitor-rs service worker — minimal stub.
// CACHE_NAME injected at release time via build script (post-Phase-0 task).
const CACHE_NAME = 'system-monitor-rs-dev';
self.addEventListener('install', (e) => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
