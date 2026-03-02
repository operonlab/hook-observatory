# Agent Vista

Pixel-art virtual office that visualizes all local LLM CLI agents in real-time.

## Architecture
- **Backend**: Go daemon (internal/) — file watching + parsing + WebSocket
- **Frontend**: React 19 + Canvas 2D (frontend/) — pixel rendering + FSM animation
- **Protocol**: WebSocket on port 8840, types in internal/protocol/ and frontend/src/types/

## Worktree Rules

This project uses two parallel worktrees. **Respect file ownership**:

### FROZEN directories (modify only on main)
- `internal/protocol/` — shared Go types
- `internal/parser/parser.go` — parser interface
- `frontend/src/types/` — shared TypeScript types
- `testdata/` — test fixtures

### wt/backend owns
- `cmd/agent-vista/`
- `internal/parser/claude/`, `internal/parser/codex/`, `internal/parser/gemini/`
- `internal/discovery/`, `internal/watcher/`, `internal/broker/`, `internal/server/`

### wt/frontend owns
- `frontend/src/` (except `frontend/src/types/`)
- `frontend/index.html`

### Shared mutable file
- `PROGRESS.md` — both worktrees read and update their own section

## Commands
- `make dev-backend` — run Go server (dev mode, no embed)
- `make dev-frontend` — run Vite dev server (HMR)
- `make test` — run all tests
- `make build` — build Go binary only (NO frontend rebuild)
- `make build-all` — **full rebuild**: frontend → cp dist → Go binary (ALWAYS use this after frontend changes)

## CRITICAL: Build Pipeline
Frontend is embedded via `//go:embed all:dist` in `web/embed.go`. After ANY frontend change:
1. MUST use `make build-all` (not `make build`, not separate steps)
2. MUST restart the binary (`pkill -f agent-vista && ./bin/agent-vista &`)
3. MUST hard-refresh browser (`Cmd+Shift+R`) to bypass JS cache
See DEV-GUIDE.md for detailed troubleshooting.

## Key Decisions
- Single binary daemon, frontend embedded via Go embed
- Zero-intrusion: read-only transcript files, no CLI modification
- Pixel Agents animation style as visual target
- Three parser adapters: Claude (JSONL incremental), Codex (JSONL incremental), Gemini (JSON diff)
