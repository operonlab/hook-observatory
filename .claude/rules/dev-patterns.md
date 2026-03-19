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

## Frontend
- **Station URLs**: Always relative paths, never absolute
- **Fill UX**: ID fields must never show raw UUIDs — use name dropdowns
- **Playwright E2E required**: Must run real browser tests after frontend work
- **SW must not intercept API**: PWA service worker must never fetch-handle /api/
- **URL**: Use `workshop.joneshong.com`, never localhost

## Architecture
- Capture: fuzzy natural-language universal intake — criterion is "whether input is ambiguous"
- Four-tier data lifecycle: Hot → Warm → Cold → Frozen (`docs/plans/four-tier-data-lifecycle.md`)
- Alembic latest migration: `m5n6o7p8q9r0`

## Scheduling
- Cronicle = sole scheduler (port 4105), launchd = boot-start + offline fallback only
- Configuration template: `schedules/manifest.json` → 透過 `seed_jobs.py` 同步到 Cronicle
- Runtime source of truth: Cronicle (port 4105)

## MCP Proxy
- mcpproxy-go v0.20.2, config `~/.mcpproxy/mcp_config.json`
- Profile switching: `mcp-profile.sh <proxy|direct|status>`
- `top_k` deprecated → use `tools_limit`

## Skill Integration
- CLI-first, MCP only when no CLI alternative exists
- `See references/` is ineffective — inline critical instructions into SKILL.md
- MANDATORY markers to prevent skipping
