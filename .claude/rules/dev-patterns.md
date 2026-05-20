# Development Patterns

## Five-Layer Coverage
Every feature must implement all applicable layers: Backend → SDK → CLI → MCP → Capture Adapter.

## Module Development
- **MCP registration**: After creating server.py, must sync `~/.mcpproxy/mcp_config.json`
- **Station restart**: `launchctl kickstart -k` — never manual kill
- **Middleware resilience**: Redis/DB calls must try/except — degrade gracefully on failure
- **Serialization sync**: New ORM field → verify `_serialize_value` can handle it
- **Partial unique index**: Soft-delete models must add `AND deleted_at IS NULL` to unique indexes
- **sync→async**: `after_create/update/delete` calling `event_bus.publish()` → must use `asyncio.ensure_future()`
- **Cache pattern**: Read-Through + Write-Invalidate at Core service layer
- **Test data purge**: Must hard-delete, not just soft-delete
- **Go `//go:embed` path basis**: relative to the `.go` file containing the directive, **not** the project root. After moving the embed source file or refactoring directory layout, verify embedded resources still resolve.

## Frontend
- **Station URLs**: Always relative paths, never absolute
- **Fill UX**: ID fields must never show raw UUIDs — use name dropdowns
- **Playwright E2E required**: Must run real browser tests after frontend work
- **SW must not intercept API**: PWA service worker must never fetch-handle /api/
- **URL**: Use `workshop.joneshong.com`, never localhost

## Architecture
- Capture: fuzzy natural-language universal intake — criterion is "whether input is ambiguous"
- Four-tier data lifecycle: Hot → Warm → Cold → Frozen (`docs/plans/four-tier-data-lifecycle.md`)
- Alembic latest migration: `m5n6o7p8q9r2`

## Scheduling
- Cronicle = sole scheduler (port 4105), launchd = boot-start + offline fallback only
- Configuration template: `schedules/manifest.json` → 透過 `seed_jobs.py` 同步到 Cronicle
- Runtime source of truth: Cronicle (port 4105)

## Port Management
- Single source of truth: `libs/sdk-client/sdk_client/port_registry.py`
- Port range convention (10000+):
  - 10000-10099: Core services
  - 10100-10199: Stations — Infra & Ops
  - 10200-10299: Stations — AI & Media
  - 10300-10399: Stations — Business & Tools
  - 10500-10599: Frontend
- Third-party / Docker ports keep their standard values
- New service → add to `port_registry.py` first, then `workshop_services.py`
- Drift check: `python3 scripts/check_nginx_ports.py`

## MCP Proxy
- mcpproxy-go v0.20.2, config `~/.mcpproxy/mcp_config.json`
- Profile switching: `mcp-profile.sh <proxy|direct|status>`
- `top_k` deprecated → use `tools_limit`

## Tmux Status Bar
- `#(...)` calls MUST use shell script (`tmux_status.sh`), **NEVER** `#(python3 ...)`
- Reason: tmux forks a subprocess per `#(cmd)` every status-interval seconds; Python startup ~1s/call × 13 = CPU 100%
- Shell + jq reads same JSON file: 0.07s/call, no residual processes

## Binary Deployment Locations (operonlab)

operonlab subtree-released binaries (hook-dispatcher / hook-observatory family) sit in two locations:

- **Local build** `~/.claude/hooks/<binary>` — newest, `make install` target, what `settings.json` hooks actually invoke
- **Homebrew tap** `/opt/homebrew/bin/<binary>` → `Cellar/<name>/<ver>/bin/<binary>` — **same-source** open-source release, lags local by days-to-weeks

**Treat brew copy as same-source-but-stale, not third-party.** E2E / critical scripts must pin to `~/.claude/hooks/` absolute path — the reason is "brew is stale", not "brew is unrelated". Don't fall back through PATH (`command -v`) in tests; it would silently pick up the stale brew copy.

## Skill Integration
- CLI-first, MCP only when no CLI alternative exists
- `See references/` is ineffective — inline critical instructions into SKILL.md
- MANDATORY markers to prevent skipping
