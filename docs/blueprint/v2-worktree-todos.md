# V2 Worktree Todo List

Each track is a git worktree (branch) that can be worked on in parallel by a separate Claude Code session.

## Setup

```bash
# From ~/workshop/ (main branch)
git worktree add ../ws-infra    -b feat/infra-foundation
git worktree add ../ws-core     -b feat/core-backend
git worktree add ../ws-web      -b feat/web-frontend
git worktree add ../ws-tools    -b feat/tools-devx
```

Each session should read THIS file first, then work through their track's tasks in order.

---

## Track 1: `feat/infra-foundation`

**Branch**: `feat/infra-foundation`
**Worktree**: `../ws-infra/`
**Scope**: `infra/`, root `docker-compose*.yml`
**Context**: Read `docs/architecture/observability.md`, `docs/architecture/folder-structure.md`

### Tasks

- [ ] **1.1 Docker Compose dev stack**
  Create `docker-compose.dev.yml` at project root with:
  - PostgreSQL 16 (port 5432, volume `pg-data`)
  - Redis 7 (port 6379, volume `redis-data`)
  - Grafana LGTM all-in-one (port 3100 grafana, 4317 OTLP)
  - Shared network `pulso-net`
  - `.env.example` with all required env vars

- [ ] **1.2 PostgreSQL init scripts**
  Create `infra/docker/postgres/`:
  - `init.sql` — Create schemas: `auth`, `finance`, `quest`, `muse`, `admin`
  - `init.sql` — Create extension: `uuid-ossp`, `pgcrypto`
  - Mount as docker-entrypoint-initdb.d volume

- [ ] **1.3 Redis configuration**
  Create `infra/docker/redis/`:
  - `redis.conf` — maxmemory 256mb, maxmemory-policy allkeys-lru
  - Stream config for EventBus (consumer groups)

- [ ] **1.4 LGTM observability stack**
  Create `infra/observability/`:
  - `otel-collector.yml` — OTLP receiver → Loki + Tempo + Mimir exporters
  - `grafana/provisioning/datasources/` — auto-provision Loki, Tempo, Mimir
  - `grafana/provisioning/dashboards/` — basic service health dashboard
  - Document access at http://localhost:3100

- [ ] **1.5 Nginx reverse proxy**
  Create `infra/nginx/`:
  - `nginx.conf` — upstream definitions for core(:8800), realtime(:8830), media(:8831)
  - `/auth/*`, `/api/*` → core
  - `/ws/*`, `/rtc/*` → realtime
  - `/` → static files (apps/web/dist/) or dev proxy
  - SSL config placeholder for production
  - `Dockerfile` for nginx container

- [ ] **1.6 Add Nginx to Docker Compose**
  Update `docker-compose.dev.yml`:
  - Nginx service (port 80, 443)
  - Depends on core, realtime, media

- [ ] **1.7 Core service Dockerfile**
  Create `services/core/Dockerfile`:
  - Multi-stage build (uv install → slim runtime)
  - Expose 8800
  - Health check endpoint

- [ ] **1.8 Dev setup script**
  Create `infra/scripts/dev-setup.sh`:
  - Check prerequisites (docker, uv, pnpm, node)
  - `docker compose -f docker-compose.dev.yml up -d` (PG + Redis + LGTM)
  - `uv sync` for Python workspace
  - `pnpm install` for JS workspace
  - Print service URLs

- [ ] **1.9 Dev teardown script**
  Create `infra/scripts/dev-teardown.sh`:
  - `docker compose -f docker-compose.dev.yml down`
  - Optional: `-v` flag to remove volumes

- [ ] **1.10 Verify & document**
  - Start full stack: `docker compose -f docker-compose.dev.yml up -d`
  - Verify PG accepts connections
  - Verify Redis ping
  - Verify Grafana dashboard loads
  - Update `docs/architecture/observability.md` with actual endpoints

---

## Track 2: `feat/core-backend`

**Branch**: `feat/core-backend`
**Worktree**: `../ws-core/`
**Scope**: `services/core/`, `services/realtime/`, `services/media/`, `libs/python/`
**Context**: Read `docs/architecture/modular-monolith.md`, `docs/architecture/event-driven.md`, `docs/architecture/auth.md`
**Note**: DB/Redis integration can be coded with connection logic but tested after Track 1 merges. Use in-memory fallback for dev without Docker.

### Tasks

- [ ] **2.1 Database connection layer**
  `services/core/src/core/db.py`:
  - Async connection pool using `psycopg_pool.AsyncConnectionPool`
  - Lifespan integration (open on startup, close on shutdown)
  - Per-request connection via FastAPI dependency
  - Config from `settings.db_url`

- [ ] **2.2 Migration runner**
  `services/core/src/core/migrations/`:
  - `runner.py` — Read SQL files, execute in order, track applied in `public.migrations` table
  - `services/core/migrations/` — SQL files named `001_<description>.sql`
  - CLI entry: `uv run python -m core.migrations.runner`

- [ ] **2.3 Auth module → PostgreSQL**
  `services/core/src/core/modules/auth/`:
  - `models.py` — `auth.users` table (id UUID PK, email UNIQUE, name, role, status, password_hash, password_salt, created_at, updated_at)
  - `services.py` — UserService (create, get_by_email, get_by_id, update_status)
  - Update `routes.py` — Replace `_users` dict with UserService
  - Migration: `migrations/001_create_auth_users.sql`

- [ ] **2.4 Finance module CRUD**
  `services/core/src/core/modules/finance/`:
  - `models.py` — `finance.transactions` (id, user_id FK, type, amount, currency, category, description, date, created_at)
  - `models.py` — `finance.budgets` (id, user_id FK, category, amount, period, created_at)
  - `services.py` — TransactionService, BudgetService
  - `routes.py` — CRUD endpoints: GET/POST/PUT/DELETE /api/finance/transactions, /api/finance/budgets
  - `schemas.py` — Request/response models
  - `events.py` — Emit `finance.transaction.created/updated/deleted`
  - Migration: `migrations/002_create_finance.sql`
  - RBAC: `finance.read`, `finance.write` permissions

- [ ] **2.5 Quest module CRUD**
  `services/core/src/core/modules/quest/`:
  - `models.py` — `quest.quests` (id, user_id, title, description, status, xp_reward, created_at), `quest.progress` (id, quest_id, user_id, status, completed_at)
  - `services.py` — QuestService, ProgressService
  - `routes.py` — CRUD + /api/quest/quests/{id}/accept, /complete, /fail
  - `schemas.py`, `events.py`
  - Migration: `migrations/003_create_quest.sql`
  - RBAC: `quest.read`, `quest.write`

- [ ] **2.6 Muse module CRUD**
  `services/core/src/core/modules/muse/`:
  - `models.py` — `muse.sparks` (id, user_id, type, title, content, tags[], created_at), `muse.links` (id, source_id FK, target_id FK, relation, created_at)
  - `services.py` — SparkService, LinkService
  - `routes.py` — CRUD + /api/muse/sparks/{id}/link
  - `schemas.py`, `events.py`
  - Migration: `migrations/004_create_muse.sql`
  - RBAC: `muse.read`, `muse.write`

- [ ] **2.7 Admin module**
  `services/core/src/core/modules/admin/`:
  - `services.py` — AdminService (list_users, update_user_role, update_user_status, system_stats)
  - `routes.py` — GET /api/admin/users, PATCH /api/admin/users/{id}, GET /api/admin/stats
  - `schemas.py`
  - RBAC: `admin.*` (admin role only)

- [ ] **2.8 EventBus Redis Streams backend**
  `services/core/src/core/events/backends/`:
  - `memory.py` — Extract current in-process backend
  - `redis_streams.py` — Redis Streams implementation (XADD, XREADGROUP, consumer group per module)
  - `bus.py` — Update EventBus to support backend selection via config
  - Config: `settings.event_backend = "memory" | "redis"`

- [ ] **2.9 Event middleware**
  `services/core/src/core/events/middleware.py`:
  - Auto-publish `system.request.received` on every request
  - Attach trace_id, user_id from session
  - Log event flow via structlog

- [ ] **2.10 OTel instrumentation**
  `services/core/src/core/middleware/telemetry.py`:
  - OpenTelemetry FastAPI instrumentation
  - Auto-tracing for all routes
  - Custom spans for EventBus publish/subscribe
  - Metrics: request count, latency histogram, event throughput
  - Export via OTLP to collector (localhost:4317)
  - Add `opentelemetry-*` deps to pyproject.toml

- [ ] **2.11 Structured logging**
  `services/core/src/core/logging.py`:
  - structlog configuration (JSON in prod, console in dev)
  - Bind trace_id, user_id to log context
  - Integration with OTel trace context

- [ ] **2.12 API error handling**
  `services/core/src/core/middleware/errors.py`:
  - Global exception handler
  - Structured error response: `{error: string, code: string, detail?: any}`
  - Map domain exceptions to HTTP status codes

- [ ] **2.13 Shared lib setup**
  `libs/python/src/corelib/`:
  - `types.py` — Shared types (Pagination, SortOrder, FilterOp)
  - `pagination.py` — Paginated query helper (offset/limit → SQL)
  - Update `libs/python/pyproject.toml`

- [ ] **2.14 Verify full integration**
  - Run Core with PostgreSQL + Redis
  - Test auth register → login → session cycle
  - Test finance CRUD
  - Test event publishing + subscribing
  - Verify OTel traces appear in Tempo

---

## Track 3: `feat/web-frontend`

**Branch**: `feat/web-frontend`
**Worktree**: `../ws-web/`
**Scope**: `apps/web/`, `libs/typescript/`
**Context**: Read `docs/architecture/frontend.md`, `docs/architecture/rwd-pwa.md`
**Note**: Can build UI with mock data first, then connect to real API after Track 2 merges.

### Tasks

- [ ] **3.1 API client layer**
  `apps/web/src/api/`:
  - `client.ts` — Base fetch wrapper with error handling, auth headers, types
  - `auth.ts` — Register, login, logout, getSession (already exists, refactor to use client)
  - `finance.ts` — Transaction CRUD, budget CRUD
  - `quest.ts` — Quest CRUD, accept/complete/fail actions
  - `muse.ts` — Spark CRUD, link CRUD
  - `admin.ts` — User management, system stats
  - Shared types matching backend schemas

- [ ] **3.2 Auth module UI**
  `apps/web/src/modules/auth/`:
  - `pages/LoginPage.tsx` — Email + password form, error display, redirect on success
  - `pages/RegisterPage.tsx` — Name + email + password + confirm, validation
  - `components/AuthGuard.tsx` — Refactor from current App.tsx inline guard
  - `components/SessionProvider.tsx` — Auto-refresh session, context provider
  - `stores/auth.ts` — Move from src/stores/, add token refresh logic

- [ ] **3.3 Finance module UI**
  `apps/web/src/modules/finance/`:
  - `pages/FinanceDashboard.tsx` — Summary cards (income, expense, balance), chart
  - `pages/TransactionList.tsx` — Sortable table, pagination, filters
  - `components/TransactionForm.tsx` — Create/edit transaction modal
  - `components/BudgetCard.tsx` — Budget vs actual progress bar
  - `stores/finance.ts` — Zustand store
  - `api/finance.ts` → import from shared api layer

- [ ] **3.4 Quest module UI**
  `apps/web/src/modules/quest/`:
  - `pages/QuestBoard.tsx` — Kanban-style board (available, in-progress, completed)
  - `pages/QuestDetail.tsx` — Quest info, progress, XP reward
  - `components/QuestCard.tsx` — Card with status badge, XP, action button
  - `components/SkillTree.tsx` — Skill tree visualization (future)
  - `stores/quest.ts` — Zustand store

- [ ] **3.5 Muse module UI**
  `apps/web/src/modules/muse/`:
  - `pages/MuseInbox.tsx` — Inbox list of sparks, create button
  - `pages/SparkDetail.tsx` — Spark viewer/editor
  - `components/SparkEditor.tsx` — Rich text editor (markdown)
  - `components/LinkGraph.tsx` — Force-directed graph of spark connections
  - `stores/muse.ts` — Zustand store

- [ ] **3.6 Admin module UI**
  `apps/web/src/modules/admin/`:
  - `pages/AdminDashboard.tsx` — System stats (users, events, uptime)
  - `pages/UserManagement.tsx` — User table with role/status edit
  - `components/UserRow.tsx` — Inline edit for role, status toggle
  - `components/SystemStats.tsx` — Real-time stats cards
  - `stores/admin.ts` — Zustand store
  - Route guard: admin role only

- [ ] **3.7 Shell enhancements**
  `apps/web/src/shell/`:
  - `NavBar.tsx` — Add notification bell, user avatar dropdown
  - `Sidebar.tsx` — Active route highlighting, collapsible on mobile
  - `Layout.tsx` — Responsive: sidebar → bottom nav on mobile
  - `AppLauncher.tsx` — Dynamic app availability based on user role/permissions
  - Toast notification system (`shared/components/Toast.tsx`)

- [ ] **3.8 Shared components**
  `apps/web/src/shared/components/`:
  - `DataTable.tsx` — Reusable sortable, paginated table
  - `Modal.tsx` — Reusable modal with backdrop, close button
  - `LoadingSpinner.tsx` — Consistent loading indicator
  - `EmptyState.tsx` — No data placeholder
  - `ErrorBoundary.tsx` — Error fallback UI

- [ ] **3.9 PWA enhancement**
  `apps/web/public/`:
  - `sw.js` — Update service worker with proper cache versioning
  - Offline fallback page
  - App update notification banner
  - Icon generation (192, 512 proper PNG, not SVG placeholders)

- [ ] **3.10 Verify & test**
  - Build passes: `pnpm build`
  - All routes navigable (/, /finance, /quest, /muse, /admin, /login)
  - Responsive at 320px, 768px, 1280px
  - PWA installable in Chrome
  - No console errors

---

## Track 4: `feat/tools-devx`

**Branch**: `feat/tools-devx`
**Worktree**: `../ws-tools/`
**Scope**: `tools/`, `docs/reference/`
**Context**: Tools are developer/operator utilities, NOT platform services. They support development workflow.
**Note**: Fully independent. No dependencies on other tracks.

### Tasks

- [ ] **4.1 Tools README**
  Create `tools/README.md`:
  - Tool catalog table (name, port, type, description)
  - Quick start guide for each tool
  - Architecture diagram (tools vs services vs infra)

- [ ] **4.2 Migrate disk-report**
  Move `~/.claude/data/disk-report/` → `tools/disk-report/`:
  - Copy source files
  - Add `pyproject.toml` with proper deps (fastapi, uvicorn, jinja2)
  - Add `README.md`
  - Update LaunchAgent plist path: `com.joneshong.disk-report.plist`
  - Verify: `uv run uvicorn tools.disk-report.web.server:app --port 9527`

- [ ] **4.3 Migrate cost-server → llm-usage**
  Move `~/.claude/data/cost-server/` → `tools/llm-usage/`:
  - Rename to `llm-usage` (clearer purpose)
  - Copy source files
  - Add `package.json`
  - Add `README.md` with API docs
  - Update LaunchAgent plist path
  - Update socket path if needed
  - Verify: service starts and tracks costs

- [ ] **4.4 Migrate tmux-webui**
  Move `~/Claude/projects/tmux-webui/` → `tools/tmux-webui/`:
  - Copy source files
  - Add `pyproject.toml` (aiohttp)
  - Add `README.md`
  - Verify: `uv run python tools/tmux-webui/server.py --port 8765`

- [ ] **4.5 Symlink general-purpose tools**
  Create symlinks for cross-project tools:
  ```bash
  ln -s ~/Claude/projects/kas-memory tools/kas-memory
  ln -s ~/Claude/projects/session-redactor tools/session-redactor
  ln -s ~/Claude/projects/claude-code-hooks-multi-agent-observability tools/observability
  ```
  These stay in their original repos but appear in `tools/` for discoverability.

- [ ] **4.6 Build system-monitor**
  Create `tools/system-monitor/`:
  - `server.py` — FastAPI app (port 9528)
  - Endpoints: GET /cpu, GET /memory, GET /disk, GET /gpu (if available), GET /all
  - Use `psutil` for system metrics
  - Simple HTML dashboard at GET /
  - Auto-refresh via SSE or polling
  - `pyproject.toml`, `README.md`

- [ ] **4.7 Developer tools documentation**
  Create `docs/reference/developer-tools.md`:
  - Overview of all tools and their purposes
  - Network map (which tool on which port)
  - How tools relate to platform services
  - Troubleshooting guide

- [ ] **4.8 Verify all tools**
  - disk-report starts and scans
  - llm-usage tracks costs
  - tmux-webui connects to tmux
  - system-monitor shows metrics
  - Symlinks resolve correctly
  - All READMEs accurate

---

## Merge Order & Checklist

After all tracks complete:

1. [ ] Merge `feat/infra-foundation` → main
2. [ ] Merge `feat/tools-devx` → main
3. [ ] Rebase `feat/core-backend` on main → merge
4. [ ] Rebase `feat/web-frontend` on main → merge
5. [ ] Full integration test: `docker compose up` + core + web
6. [ ] Update `CLAUDE.md` if needed
7. [ ] Tag release: `v2.0.0-alpha`
