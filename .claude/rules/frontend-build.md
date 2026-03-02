# Frontend Build Rule

Nginx serves `workbench/dist/` as static files (NOT proxied to dev server).

## After ANY workbench source change

Rebuild with correct BASE_PATH:
```bash
cd /Users/joneshong/workshop/workbench && BASE_PATH=/v2 /opt/homebrew/Cellar/node@22/22.22.0/lib/node_modules/corepack/shims/pnpm run build
```

The build script automatically injects `git rev-parse --short HEAD` into `dist/sw.js` CACHE_NAME,
so every build produces a new SW version → browser detects byte-diff → installs new SW → purges old cache.

## Verify after build

```bash
grep -o 'src="[^"]*"' workbench/dist/index.html   # must show /v2/static/...
head -1 workbench/dist/sw.js                        # must show workshop-<git-hash>
```

## Key facts

- `BASE_PATH=/v2` is REQUIRED — without it, asset paths miss `/v2/` prefix → 404
- Nginx `/v2/` block already has `Cache-Control: no-store` → sw.js always fetched fresh
- SW CACHE_NAME uses git hash (injected at build) — no manual version bump needed
- Incognito / browser cache clear does NOT clear SW CacheStorage — only SW version change clears it
