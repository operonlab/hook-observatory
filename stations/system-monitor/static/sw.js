// System Monitor Service Worker
// 策略：HTML = network-first, 靜態資源 = stale-while-revalidate, API = 不快取

const CACHE_NAME = 'sysmon-v1';

// 預快取的核心靜態資源（相對於 SW 所在位置 /static/）
const PRECACHE_ASSETS = [
  '../',                       // 首頁 HTML
  'css/dashboard.css',
  'js/dashboard.js',
  'manifest.json',
  'icons/icon-192.svg',
  'icons/icon-512.svg',
];

// 第三方 CDN 資源（stale-while-revalidate）
const CDN_ORIGINS = [
  'cdn.jsdelivr.net',
  'fonts.googleapis.com',
  'fonts.gstatic.com',
];

// ─── 安裝：預快取核心資源 ───
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_ASSETS))
      .then(() => self.skipWaiting())
  );
});

// ─── 啟用：清理舊版快取 ───
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

// ─── 攔截請求 ───
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 跳過非 GET 請求
  if (event.request.method !== 'GET') return;

  // 跳過 API 路由（監控資料必須即時）
  if (isApiRequest(url)) return;

  // HTML 頁面：network-first（確保最新 UI）
  if (isNavigationRequest(event.request)) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // CDN 資源 + 本地靜態資源：stale-while-revalidate
  if (isStaticAsset(url) || isCdnResource(url)) {
    event.respondWith(staleWhileRevalidate(event.request));
    return;
  }
});

// ─── 判斷函數 ───

function isApiRequest(url) {
  const path = url.pathname;
  // FastAPI 端的 API 路徑（經 Nginx 代理後在 /v2/apps/sysmon/ 下）
  return path.includes('/status') ||
         path.includes('/services') ||
         path.includes('/health') ||
         path.includes('/history') ||
         path.includes('/alerts') ||
         path.includes('/disk/') ||
         path.includes('/reports') ||
         path.includes('/guardian');
}

function isNavigationRequest(request) {
  return request.mode === 'navigate' ||
         (request.headers.get('accept') || '').includes('text/html');
}

function isStaticAsset(url) {
  return url.pathname.match(/\.(css|js|svg|png|jpg|jpeg|woff2?|ttf|json)$/);
}

function isCdnResource(url) {
  return CDN_ORIGINS.some((origin) => url.hostname.includes(origin));
}

// ─── 快取策略 ───

// Network-first：優先網路，失敗回退快取
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    // 離線且無快取時回傳基本離線提示
    return new Response(
      '<!DOCTYPE html><html><head><meta charset="utf-8"><title>離線</title>' +
      '<style>body{background:#1e1e2e;color:#cdd6f4;font-family:sans-serif;' +
      'display:flex;justify-content:center;align-items:center;height:100vh;margin:0}' +
      '.box{text-align:center}h1{color:#cba6f7}p{color:#a6adc8}</style></head>' +
      '<body><div class="box"><h1>System Monitor</h1>' +
      '<p>目前離線，請檢查網路連線後重試。</p></div></body></html>',
      { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
    );
  }
}

// Stale-while-revalidate：先回傳快取，同時背景更新
async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);

  // 背景更新（不等待）
  const fetchPromise = fetch(request)
    .then((response) => {
      if (response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  // 有快取就先回傳，沒有就等網路
  if (cached) return cached;
  const response = await fetchPromise;
  if (response) return response;

  return new Response('Resource unavailable', { status: 503 });
}
