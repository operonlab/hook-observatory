# Workshop V2 Blueprint

## Vision

Pulso — Modular Monolith + Event-Driven platform with RBAC/ABAC, Hook/Plugin extensibility, and comprehensive developer tooling. Single deployable backend + hot-path services + unified React frontend.

## Architecture Recap

```
                    ┌─────────────────────────────────────┐
                    │            Nginx (reverse proxy)     │
                    │  :443 → TLS termination              │
                    └───┬──────────┬──────────┬────────────┘
                        │          │          │
                   /auth, /api  /ws, /rtc   /tools
                        │          │          │
              ┌─────────▼──┐  ┌───▼────┐  ┌──▼──────────┐
              │   Core     │  │Realtime│  │  Tools UIs  │
              │  :8800     │  │ :8830  │  │  (各自 port) │
              │            │  └───┬────┘  └─────────────┘
              │  modules:  │      │
              │  - auth    │      │ LiveKit
              │  - finance │      │ WebRTC
              │  - quest   │      │
              │  - muse    │  ┌───▼────┐
              │  - admin   │  │ Media  │
              │            │  │ :8831  │
              │  engines:  │  └────────┘
              │  - EventBus│
              │  - HookBus │
              │  - RBAC+ABAC
              └──┬─────┬───┘
                 │     │
           ┌─────▼─┐ ┌─▼──────┐
           │  PG   │ │ Redis  │
           │:5432  │ │ :6379  │
           └───────┘ └────────┘
```

**Deploy Units**: Core (1) + Realtime (1) + Media (1) = 3 services
**Frontend**: Single React app (`apps/web/`) with domain module code-splitting
**Database**: PostgreSQL with per-module schema isolation (`auth.*`, `finance.*`, etc.)
**Events**: In-process EventBus → Redis Streams (future scaling)
**Observability**: OpenTelemetry → LGTM (dev) / SigNoz (prod)

## Tool Classification Decision

### Judgment Criteria

| Criteria | Platform Service | Developer Tool |
|----------|-----------------|---------------|
| Audience | Platform users | Developer/operator |
| Remove it | Users lose features | Platform unaffected |
| Auth | RBAC/ABAC gated | No auth (localhost) |
| EventBus | Produces/consumes events | No participation |
| DB | PostgreSQL (shared) | SQLite/flat files (own) |

### Classification Result

**Platform Services** (`services/core/modules/`):
- auth, finance, quest, muse, admin

**Developer Tools** (`tools/`):

| Tool | Current Location | Type | Web UI | Action |
|------|-----------------|------|--------|--------|
| sandbox-executor | `workshop/tools/` | MCP Server | - | Already here |
| kas-memory | `~/Claude/projects/kas-memory/` | MCP Server | - | Symlink + doc |
| session-redactor | `~/Claude/projects/session-redactor/` | Scanner | - | Symlink + doc |
| observability | `~/Claude/projects/claude-code-hooks-*` | Full Stack | :5173 | Symlink + doc |
| tmux-webui | `~/Claude/projects/tmux-webui/` | Web Server | :8765 | Migrate |
| disk-report | `~/.claude/data/disk-report/` | FastAPI | :9527 | Migrate |
| cost-server | `~/.claude/data/cost-server/` | Service | - | Migrate → llm-usage |
| system-monitor | (new) | FastAPI | :9528 | Build new |

### Migration Strategy

**General-purpose tools** (KAS Memory, session-redactor, observability):
- Keep source in `~/Claude/projects/` (own git repos, cross-project usage)
- Symlink into `tools/` for discoverability: `tools/<name> → ~/Claude/projects/<name>`
- Document in `tools/README.md`

**Workshop-specific tools** (disk-report, cost-server, system-monitor, tmux-webui):
- Physically move into `tools/` with proper project structure
- Update LaunchAgent plists and configs

## 4 Parallel Tracks (Worktrees)

### Dependency Map

```
Track 1: infra ──────────────────────────────────────→ merge
Track 2: core  ──── (needs PG/Redis from T1) ──────→ merge
Track 3: web   ──── (needs API contracts from T2) ──→ merge
Track 4: tools ──────────────────────────────────────→ merge
         │                                              │
         ▼                                              ▼
      All can START immediately        Merging: T1 first → T4 → T2 → T3
      (directory isolation)            (minimize conflicts)
```

### File Isolation

| Track | Directories (exclusive) | Shared files |
|-------|------------------------|-------------|
| 1. infra | `infra/`, `docker-compose*.yml` | - |
| 2. core | `services/`, `libs/python/` | `pyproject.toml` (root) |
| 3. web | `apps/web/`, `libs/typescript/` | `package.json` (root) |
| 4. tools | `tools/`, `docs/reference/` | - |

Conflict risk: LOW. Only root config files may need merge resolution.

### Track 1: `feat/infra-foundation`

**Scope**: Docker, PostgreSQL, Redis, LGTM, Nginx
**Dependencies**: None (can start immediately)
**Estimated tasks**: 10

Core deliverables:
- `docker-compose.dev.yml` with PG + Redis + LGTM + Nginx
- PostgreSQL init scripts (schema per module)
- Redis config (event streams + cache)
- LGTM stack (Grafana + Loki + Tempo + Mimir in single container)
- Nginx reverse proxy config
- OTel collector config
- Dev setup script (`infra/scripts/dev-setup.sh`)

### Track 2: `feat/core-backend`

**Scope**: Core monolith modules, DB integration, Redis EventBus
**Dependencies**: Track 1 for PostgreSQL/Redis (but can code without running DB)
**Estimated tasks**: 14

Core deliverables:
- PostgreSQL connection pool (psycopg async)
- Migration runner (SQL files per module)
- Auth module: user store → PostgreSQL
- Finance module: transactions, budgets CRUD
- Quest module: quests, progress CRUD
- Muse module: sparks, links CRUD
- Admin module: user management, system stats
- EventBus upgrade: Redis Streams backend
- OTel instrumentation (traces + metrics)
- API error handling middleware

### Track 3: `feat/web-frontend`

**Scope**: React domain modules, auth flow, responsive UI
**Dependencies**: Track 2 for API contracts (can build with mock data first)
**Estimated tasks**: 10

Core deliverables:
- Auth module: login/register pages, protected routes, session refresh
- Finance module: transaction list, create/edit forms
- Quest module: quest board, quest cards, progress tracking
- Muse module: spark editor, link graph visualization
- Admin module: user management table, system dashboard
- Shared: toast notifications, loading states, error boundaries
- PWA: offline shell, service worker update flow
- RWD: responsive polish at all breakpoints

### Track 4: `feat/tools-devx`

**Scope**: Tool migration, consolidation, documentation
**Dependencies**: None (can start immediately)
**Estimated tasks**: 8

Core deliverables:
- `tools/README.md` — unified tool catalog
- Migrate disk-report → `tools/disk-report/`
- Migrate cost-server → `tools/llm-usage/`
- Migrate tmux-webui → `tools/tmux-webui/`
- Build system-monitor → `tools/system-monitor/`
- Symlink general-purpose tools (kas-memory, session-redactor, observability)
- `docs/reference/developer-tools.md`
- Update LaunchAgent plists

## Merge Strategy

1. **Track 1 (infra)** merges first — provides foundation
2. **Track 4 (tools)** merges second — independent, no conflicts
3. **Track 2 (core)** merges third — may need rebase for root pyproject.toml
4. **Track 3 (web)** merges last — may need rebase for API type updates

## Out of Scope (Future Sprints)

- Production deployment (SigNoz, CI/CD, k8s)
- LiveKit/WebRTC implementation (realtime service)
- STT/TTS processing (media service)
- Plugin marketplace & distribution
- Full business logic (complex finance rules, quest chains, etc.)
- Mobile-specific optimizations
- E2E testing framework
