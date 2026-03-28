# Workshop

Modular Monolith + Event-Driven workspace.

## Stack
- **Backend**: Python 3.12 / FastAPI / uv (Modular Monolith, port 10000)
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
- `libs/` — Shared libraries: `sdk-client/` (38 API clients + utils), `audio-ops/` (operators), `tmux-lib/`, `ai-assistant/` (TS), `live2d-core/` (TS)
- `core/cli/` — Core module CLI wrappers
- `docs/` — Architecture + Vision (Traditional Chinese, source of truth)
- `vendor/` — Third-party tools; `plugins/` — Plugin packages
- `lab/` — POC experiments; `infra/` — Docker, Nginx, observability; `scripts/` — Build/deploy

## Multi-Machine Rules
- **Alembic migration 只在 Mac 主機跑** — 遠端 Claude Code 不可執行 `alembic revision` 或 `alembic upgrade`
- **Fleet dispatch** 時 Claude Code 使用 `--allowedTools` 白名單，非 `--dangerously-skip-permissions`
- **Git branch 隔離** — 遠端工作一律在 `fleet/task-*` branch，不碰 main
- **Mac 不依賴 Windows** — Tailscale 斷線不影響 Mac 服務

## Session Naming
On receiving the FIRST user message of a session, rename the session using the built-in `/rename <title>` CLI command (NOT the Skill tool — `/rename` is a built-in command).
Rules: verb-first, kebab-case, max 30 chars, 2-4 words.
Examples: `fix-auth-middleware`, `add-paper-search`, `refactor-memvault-scoring`, `explore-testing-types`
