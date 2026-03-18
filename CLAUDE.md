# Workshop

Modular Monolith + Event-Driven workspace.

## Stack
- **Backend**: Python 3.12 / FastAPI / uv (Modular Monolith, port 8801)
- **Frontend**: React 19 / TypeScript / Rsbuild / pnpm (Single App, port 3000)
- **Database**: PostgreSQL (per-module schema isolation)
- **Cache/Events**: Redis (cache + event bus)
- **Storage**: RustFS (MinIO fork, S3-compatible)
- **Realtime**: LiveKit (WebRTC), SSE (streaming)
- **Observability**: OpenTelemetry + LGTM (dev) / SigNoz (prod)

## Key Directories
- `core/src/modules/` — 17 domain modules (auth, admin, briefing, capture, dailyos, finance, ideagraph, intelflow, invest, matchcore, memvault, nodeflow, notification, paper, skillpath, taskflow, workpool)
- `core/services/` — Hot-path: realtime (8830), media (8831)
- `workbench/` — Single React app
- `mcp/` — 23 MCP servers (SDK-based protocol access)
- `stations/` — 19 standalone local tools (each with `cli/`)
- `bridges/` — External connectors (LINE, Telegram, Discord)
- `libs/` — Shared libraries (python + typescript); SDK: `libs/python/src/workshop/clients/` (20+ clients)
- `core/cli/` — Core module CLI wrappers
- `docs/` — Architecture + Vision (Traditional Chinese, source of truth)
- `vendor/` — Third-party tools; `plugins/` — Plugin packages
- `lab/` — POC experiments; `infra/` — Docker, Nginx, observability; `scripts/` — Build/deploy

## Session Naming
On receiving the FIRST user message of a session, immediately run `/rename <title>`.
Rules: verb-first, kebab-case, max 30 chars, 2-4 words.
Examples: `fix-auth-middleware`, `add-paper-search`, `refactor-memvault-scoring`, `explore-testing-types`
