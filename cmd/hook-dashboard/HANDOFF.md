# Hook Dashboard — HANDOFF

Phase 1 MVP completed 2026-05-16. Next session picks up here.

## Already done (MVP)

- [x] `cmd/hook-dashboard/main.go` — net/http server, 8 endpoints, in-memory aggregation from spool jsonl
- [x] `cmd/hook-dashboard/static/index.html` — vanilla SPA (3 cards + 3 tables + filterable events)
- [x] Binary at `~/.local/bin/hook-dashboard` (listens 127.0.0.1:10100)
- [x] Nginx route `/apps/hook/` → 127.0.0.1:10100 with auth_request (workshop-apps.inc:149)
- [x] `workbench/src/shared/constants/apps.ts` — restored "Hook 監控台" entry
- [x] `workbench/dist/` rebuilt with new entry
- [x] E2E verified: direct binary serves 13675 events; nginx route returns 302→login (correct auth gate)

## Outstanding (Tier 3 Full target = 20-30h)

### Persistence
- [ ] launchd plist `~/Library/LaunchAgents/com.joneshong.scheduler.hook-dashboard.plist` (currently `nohup` only — dies on reboot)
- [ ] `scripts/workshop_services.py` SERVICES entry
- [ ] `libs/sdk-client/sdk_client/port_registry.py` PORTS["hook-dashboard"] = 10100 (formal registration)

### Data layer (replace in-memory cache)
- [ ] Go spool drainer (port `_archive/hook-observatory-py/spool.py` logic) — reads jsonl, dedup_hash, writes to PG
- [ ] PostgreSQL `hook_observatory` schema (was archived 2026-05-13 — verify if dropped; if so re-create from `_archive/.../models.py`)
- [ ] Replace SQL queries in Go (currently in-memory `compute*` functions)
- [ ] Performance: 13k events in 44MB jsonl → cold load ~50ms; OK for now, but won't scale past ~100k

### Frontend port (replace vanilla HTML)
- [ ] Port React/Recharts SPA from `_archive/hook-observatory-py/frontend/src/` (828 LoC, 2 pages + 7 components + i18n)
- [ ] pnpm build → `dist/` → embed in Go binary via `go:embed`
- [ ] Replace 4 charts: EventTypeChart / TimelineChart / ToolUsageChart / SessionList

### Observability
- [ ] `stations/sentinel/checker.py` LIGHT_CHECKS + DEEP_CHECKS for `hook-dashboard`
- [ ] `stations/sentinel/remediation.py` SIMPLE_RESTART_MAP entry

### Polish
- [ ] Cookie auth middleware (currently relies on nginx auth_request only)
- [ ] i18n backend (zh-TW + en) — frontend has it, Go side none
- [ ] CORS config
- [ ] FeatureStore telemetry hooks (optional, was in Python)

## Reference

- Python source of truth: `stations/_archive/hook-observatory-py/` (routes.py / models.py / frontend/src/)
- Schema (from archive): `event_type`, `session_id`, `tool_name`, `hook_name`, `payload` (JSONB), `dedup_hash`, `created_at`
- Spool format: `{event_type, ts, data}` JSON Lines
- Spool path: `~/.hook-observatory/spool/` (events.jsonl + cursor.json + *.processing)
- Existing Go pattern reference: `cmd/hook-observatory/main.go`
- Nginx auth pattern reference: `sentinel` block at workshop-apps.inc

## Quick commands

```bash
# Build + install
cd ~/workshop/stations/hook-observatory
go build -ldflags="-s -w" -o bin/hook-dashboard ./cmd/hook-dashboard
cp bin/hook-dashboard ~/.local/bin/hook-dashboard

# Run (currently)
nohup ~/.local/bin/hook-dashboard -addr 127.0.0.1:10100 > /tmp/hook-dashboard.log 2>&1 &

# Test direct
curl http://127.0.0.1:10100/api/stats/summary

# Test via nginx (needs auth cookie)
open https://workshop.joneshong.com/apps/hook/
```
