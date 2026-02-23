---
doc_version: 2
content_hash: 85d21b7c
---

# V2 Worktree Todo List (Revised)

> NOT a migration. Rebuild everything from V1 documentation + V2 architecture with maximum code reuse.
> Reference: `v1-feature-inventory.md` for V1 features, `v2-blueprint.md` for V2 design.

## Setup

```bash
# From ~/workshop/ (main branch, after blueprint commit)
git worktree add ../ws-infra    -b feat/infra-db
git worktree add ../ws-engine   -b feat/core-engine
git worktree add ../ws-modules  -b feat/domain-modules
git worktree add ../ws-web      -b feat/web-complete
```

**Important for each session**:
- Read `docs/blueprint/v2-blueprint.md` for architecture decisions
- Read `docs/blueprint/v1-feature-inventory.md` for V1 reference
- Use Sonnet agents (not Haiku). Do NOT use external CLIs (Codex/Gemini).
- Each track works only in its designated directories.

---

## Track 1: `feat/infra-db`

**Branch**: `feat/infra-db`
**Worktree**: `../ws-infra/`
**Scope**: `infra/`, `docker-compose*.yml`, `core/migrations/`
**Dependencies**: None

### Tasks

- [ ] **1.1 Docker Compose dev stack**
  Create `docker-compose.dev.yml`:
  - PostgreSQL 16 (port 5432, user: workshop, db: workshop_dev)
  - Redis 7 (port 6379)
  - Grafana LGTM all-in-one `grafana/otel-lgtm` (ports: 3100 grafana, 4317 OTLP gRPC, 4318 OTLP HTTP)
  - Network: `workshop-net`
  - Volumes: `pg-data`, `redis-data`
  - `.env.example` with all vars

- [ ] **1.2 PostgreSQL init schemas**
  `infra/docker/postgres/init.sql`:
  ```sql
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
  CREATE EXTENSION IF NOT EXISTS "pgcrypto";
  CREATE SCHEMA IF NOT EXISTS auth;
  CREATE SCHEMA IF NOT EXISTS finance;
  CREATE SCHEMA IF NOT EXISTS quest;
  CREATE SCHEMA IF NOT EXISTS muse;
  CREATE SCHEMA IF NOT EXISTS admin;
  ```
  Mount as `docker-entrypoint-initdb.d` volume.

- [ ] **1.3 Auth migration SQL**
  `core/migrations/001_auth.sql`:
  - `auth.users` (id UUID PK, email UNIQUE, display_name, avatar_url, role, status, timestamps)
  - `auth.local_credentials` (user_id FK PK, password_hash, email_verified)
  - `auth.oauth_accounts` (id, user_id FK, provider, provider_user_id, email, tokens, raw_profile JSONB, UNIQUE(provider, provider_user_id))
  - `auth.webauthn_credentials` (id, user_id FK, credential_id BYTEA UNIQUE, public_key BYTEA, sign_count, aaguid, transports, backup fields, device_name)
  - `auth.sessions` (id VARCHAR PK, user_id FK, ip_address INET, user_agent, expires_at, last_active_at)
  - All indexes

- [ ] **1.4 Finance migration SQL**
  `core/migrations/002_finance.sql`:
  - `finance.transactions` (id, user_id, type enum, amount decimal, currency, category, description, date, tags[], created_at, updated_at)
  - `finance.budgets` (id, user_id, category, amount, period enum, start_date, created_at)
  - `finance.categories` (id, user_id, name, icon, color, type, sort_order)

- [ ] **1.5 Quest migration SQL**
  `core/migrations/003_quest.sql`:
  - `quest.quests` (id, creator_id, title, description, status enum, xp_reward, difficulty, tags[], deadline, created_at)
  - `quest.progress` (id, quest_id, user_id, status enum, started_at, completed_at)
  - `quest.skills` (id, user_id, name, category, xp_total, level)

- [ ] **1.6 Muse migration SQL**
  `core/migrations/004_muse.sql`:
  - `muse.sparks` (id, user_id, type enum, title, content text, tags[], metadata JSONB, created_at, updated_at)
  - `muse.links` (id, source_id FK, target_id FK, relation varchar, strength float, created_at)

- [ ] **1.7 Redis configuration**
  `infra/docker/redis/redis.conf`:
  - maxmemory 256mb, allkeys-lru
  - Stream config documentation for EventBus consumer groups

- [ ] **1.8 Nginx reverse proxy**
  `infra/nginx/nginx.conf`:
  - Upstream: core(:8800), realtime(:8830), media(:8831), web(:3000 dev)
  - Routes: /auth/*, /api/* → core; /ws/*, /rtc/* → realtime; / → web
  - Security headers (X-Frame-Options, CSP, HSTS)
  - `infra/nginx/Dockerfile`

- [ ] **1.9 LGTM observability config**
  `infra/observability/`:
  - `otel-collector.yml` — receivers (OTLP gRPC + HTTP), exporters (Loki, Tempo, Prometheus)
  - `grafana/provisioning/dashboards/workshop-overview.json` — basic dashboard

- [ ] **1.10 Dev scripts**
  `infra/scripts/dev-setup.sh`:
  - Check prereqs (docker, uv, pnpm)
  - `docker compose -f docker-compose.dev.yml up -d`
  - Wait for PG ready (`pg_isready`)
  - Run migrations
  - `uv sync && pnpm install`
  - Print service URLs

  `infra/scripts/dev-teardown.sh`:
  - `docker compose down [-v]`

- [ ] **1.11 Verify**
  - `docker compose up -d` → all services healthy
  - PG: `psql -c '\dn'` shows 5 schemas
  - PG: all tables created with correct columns
  - Redis: `redis-cli ping` → PONG
  - Grafana: http://localhost:3100 loads

---

## Track 2: `feat/core-engine`

**Branch**: `feat/core-engine`
**Worktree**: `../ws-engine/`
**Scope**: `libs/python/`, `core/src/` (events, hooks, middleware, modules/auth, shared, config, main, db)
**Dependencies**: None to start. Needs T1 for DB testing.
**V1 Reference**: Auth section of `v1-feature-inventory.md`

### Tasks

- [ ] **2.1 Python shared lib — DB layer**
  `libs/python/src/corelib/db/`:
  - `pool.py` — `create_pool(db_url) → AsyncConnectionPool` (psycopg 3 async), lifespan helpers
  - `migrations.py` — `MigrationRunner` — read `migrations/*.sql`, track in `public.schema_migrations`, CLI entry

- [ ] **2.2 Python shared lib — Base classes**
  `libs/python/src/corelib/`:
  - `schemas.py` — `PaginatedResponse[T]`, `ErrorResponse`, `SortOrder`, `FilterOp`, `Pagination`
  - `repository.py` — `BaseRepository[T]` — generic async CRUD against psycopg pool, pagination support
  - `service.py` — `BaseService[T]` — wraps BaseRepository + auto permission check + auto event emission
  - `router.py` — `create_crud_router()` — generates GET (list), GET/{id}, POST, PUT/{id}, DELETE/{id} from service + schemas + permission map
  - `events.py` — `CRUDEventMixin` — auto-emit `{domain}.{entity}.{created|updated|deleted}`
  - `health.py` — `create_health_router(name, version, checks: list)` — /health + /health/ready
  - Update `libs/python/pyproject.toml` (deps: psycopg[pool], pydantic, structlog)

- [ ] **2.3 Python shared lib — Auth abstractions**
  `libs/python/src/corelib/auth/`:
  - `provider.py` — `AuthProvider` ABC (`authenticate()`, `provider_name`)
  - `session.py` — `SessionManager` (create, validate, revoke, list by user; DB-backed with TTL; signed cookie with session ID)
  - `deps.py` — `get_current_user(request)`, `require_role(*roles)`, `require_permission(perm)`
  - `types.py` — `AuthResult`, `UserIdentity`, `SessionPayload`

- [ ] **2.4 Python shared lib — Middleware**
  `libs/python/src/corelib/middleware/`:
  - `errors.py` — Global exception handler → `{"error": str, "code": str, "detail": any, "trace_id": str}`
  - `logging.py` — structlog config (JSON prod, console dev), bind trace_id + user_id
  - `telemetry.py` — OTel FastAPI instrumentation, custom spans for EventBus
  - `rate_limit.py` — slowapi wrapper, per-route limits, Redis backend support

- [ ] **2.5 Core config update**
  `core/src/config.py`:
  - Add: `webauthn_rp_id`, `webauthn_rp_name`, `webauthn_origin`
  - Add: `github_client_id`, `github_client_secret`
  - Add: `google_client_id`, `google_client_secret`
  - Add: `public_base_url` (for OAuth redirect URIs)
  - Add: `session_secret` (for cookie signing)
  - Keep: db_url, redis_url, cors_origins, event_backend, plugin_dir

- [ ] **2.6 Core DB integration**
  `core/src/db.py`:
  - Use `corelib.db.create_pool(settings.db_url)`
  - Integrate into FastAPI lifespan (open on startup, close on shutdown)
  - FastAPI dependency: `get_pool()`, `get_conn()`

- [ ] **2.7 Auth module — Email/Password provider**
  `core/src/modules/auth/providers/email.py`:
  - `EmailPasswordProvider(AuthProvider)`
  - Register: validate email + password(>=8) → bcrypt hash → create user + local_credentials
  - Login: verify email + bcrypt → return AuthResult
  - Use passlib CryptContext(schemes=["bcrypt"])

- [ ] **2.8 Auth module — GitHub OAuth provider**
  `core/src/modules/auth/providers/github.py`:
  - `GitHubOAuthProvider(AuthProvider)`
  - Use authlib: register github oauth, authorize_redirect, authorize_access_token
  - Fetch /user + /user/emails (primary verified email)
  - Return AuthResult with provider_user_id = github user id
  - Allowlist support (optional env var)

- [ ] **2.9 Auth module — Google OAuth provider**
  `core/src/modules/auth/providers/google.py`:
  - `GoogleOAuthProvider(AuthProvider)`
  - Use authlib: OIDC discovery, authorize_redirect, authorize_access_token
  - PKCE enabled (code_challenge_method: S256)
  - Extract userinfo from ID token
  - Google One Tap: POST endpoint, verify with google-auth library
  - Return AuthResult with provider_user_id = sub claim

- [ ] **2.10 Auth module — Passkey provider**
  `core/src/modules/auth/providers/passkey.py`:
  - `PasskeyProvider(AuthProvider)`
  - Use py_webauthn (webauthn>=2.7.1)
  - Registration: generate_registration_options → verify_registration_response → store credential (BYTEA)
  - Authentication: generate_authentication_options → verify_authentication_response → update sign_count
  - Credential management: list, delete

- [ ] **2.11 Auth module — Service + Routes**
  `core/src/modules/auth/`:
  - `service.py` — `AuthService` orchestrator: authenticate(provider, **kwargs), link_account(), create_session(), revoke_session()
  - Account linking: check provider_user_id → check email → create new user
  - `routes.py` — All endpoints from blueprint (register, login, logout, session, OAuth flows, Passkey flows, provider management)
  - `repository.py` — `UserRepository`, `OAuthAccountRepository`, `WebAuthnCredentialRepository`, `SessionRepository`
  - `schemas.py` — Request/response Pydantic models for all endpoints

- [ ] **2.12 Auth module — RBAC + ABAC**
  Rewrite `core/src/modules/auth/permissions.py`:
  - Keep ROLE_PERMISSIONS dict (admin, user, guest)
  - Keep PolicyEngine with RequestContext
  - Integrate with corelib deps: `require_permission()` auto-checks RBAC + ABAC
  - Add policies: suspended_users_blocked, owner_only_write, rate_limited

- [ ] **2.13 EventBus — Redis Streams backend**
  `core/src/events/backends/`:
  - `memory.py` — Extract current in-process implementation
  - `redis_streams.py` — XADD, XREADGROUP, consumer groups per module
  - `core/src/events/bus.py` — Backend selection via settings.event_backend

- [ ] **2.14 Core main.py update**
  - Wire up: db pool, all auth providers, auth service, session middleware
  - Add: Starlette SessionMiddleware (for OAuth state)
  - Add: OTel middleware, structured logging, global error handler, rate limiting
  - Mount: auth router, health router
  - Lifespan: db pool open/close, event_bus start/stop, hook_bus load_plugins

- [ ] **2.15 Verify full auth flow**
  - Register via email/password → session created → /auth/session returns user
  - Login → session → logout → session revoked
  - OAuth flow (mock or real if keys available)
  - Passkey registration + authentication (test with Chrome)
  - RBAC: admin can access admin routes, user cannot
  - Rate limiting: 6th login attempt in 1 minute → 429

---

## Track 3: `feat/domain-modules`

**Branch**: `feat/domain-modules`
**Worktree**: `../ws-modules/`
**Scope**: `core/src/modules/{finance,quest,muse,admin}/`
**Dependencies**: Needs T2 base classes (BaseService, BaseRepository, create_crud_router). Can stub them initially.
**Strategy**: If T2 isn't merged yet, define minimal interfaces inline and refactor on merge.

### Tasks

- [ ] **3.1 Finance module — Repository + Service**
  `core/src/modules/finance/`:
  - `repository.py`:
    - `TransactionRepo(BaseRepository[Transaction])` — schema="finance", table="transactions"
    - `BudgetRepo(BaseRepository[Budget])` — schema="finance", table="budgets"
    - `CategoryRepo(BaseRepository[Category])` — custom: default categories seeding
  - `services.py`:
    - `TransactionService(BaseService[Transaction])` — domain="finance"
    - Custom: `get_monthly_summary(user_id, year, month)`, `get_by_category(user_id, category)`
    - `BudgetService(BaseService[Budget])` — custom: `check_budget_alert(user_id, category)`

- [ ] **3.2 Finance module — Routes + Schemas**
  - `schemas.py`:
    - `TransactionCreate` (type: income|expense, amount: Decimal, currency, category, description, date, tags)
    - `TransactionUpdate` (all optional)
    - `TransactionResponse` (id, + all fields + created_at)
    - `TransactionFilter` (type, category, date_from, date_to, amount_min, amount_max)
    - `MonthlySummary` (income, expense, balance, by_category: list)
    - Same pattern for Budget, Category
  - `routes.py`:
    - CRUD via `create_crud_router("/api/finance/transactions", ...)` permissions: finance.read/write
    - Custom: `GET /api/finance/summary?year=&month=` → MonthlySummary
    - CRUD for budgets, categories
  - `events.py`:
    - Constants: `TRANSACTION_CREATED/UPDATED/DELETED`, `BUDGET_CREATED/EXCEEDED`
    - Handler: on transaction_created → check budget → emit budget_exceeded if over

- [ ] **3.3 Quest module — Repository + Service**
  `core/src/modules/quest/`:
  - `repository.py`:
    - `QuestRepo(BaseRepository[Quest])` — schema="quest", table="quests"
    - `ProgressRepo(BaseRepository[Progress])` — schema="quest", table="progress"
    - `SkillRepo(BaseRepository[Skill])` — schema="quest", table="skills"
  - `services.py`:
    - `QuestService(BaseService[Quest])` — domain="quest"
    - Custom: `accept(quest_id, user_id)`, `complete(quest_id, user_id)`, `fail(quest_id, user_id)`
    - XP calculation: on complete → update skill XP → recalculate level
    - `SkillService` — `get_skill_tree(user_id)`, `add_xp(user_id, skill_name, amount)`

- [ ] **3.4 Quest module — Routes + Schemas**
  - `schemas.py`: QuestCreate, QuestResponse, QuestFilter, ProgressResponse, SkillResponse, SkillTree
  - `routes.py`:
    - CRUD quests: `/api/quest/quests` (permissions: quest.read/write)
    - Actions: `POST /api/quest/quests/{id}/accept`, `/complete`, `/fail`
    - Skills: `GET /api/quest/skills` (user's skill tree), `GET /api/quest/skills/{id}`
    - Board: `GET /api/quest/board` (grouped by status)
  - `events.py`: QUEST_CREATED/ACCEPTED/COMPLETED/FAILED, SKILL_XP_GAINED/LEVEL_UP

- [ ] **3.5 Muse module — Repository + Service**
  `core/src/modules/muse/`:
  - `repository.py`:
    - `SparkRepo(BaseRepository[Spark])` — custom: full-text search on title+content, tag filtering
    - `LinkRepo(BaseRepository[Link])` — custom: get_graph(user_id), get_connected(spark_id)
  - `services.py`:
    - `SparkService(BaseService[Spark])` — domain="muse"
    - Custom: `search(user_id, query, tags)`, `get_inbox(user_id)` (recent unlinked sparks)
    - `LinkService` — `link(source_id, target_id, relation)`, `unlink(link_id)`, `get_graph(user_id)`

- [ ] **3.6 Muse module — Routes + Schemas**
  - `schemas.py`: SparkCreate, SparkResponse, SparkFilter, LinkCreate, LinkResponse, GraphResponse
  - `routes.py`:
    - CRUD sparks: `/api/muse/sparks` (permissions: muse.read/write)
    - Search: `GET /api/muse/sparks/search?q=&tags=`
    - Inbox: `GET /api/muse/sparks/inbox`
    - Links: `POST /api/muse/links`, `DELETE /api/muse/links/{id}`
    - Graph: `GET /api/muse/graph`
  - `events.py`: SPARK_CREATED/UPDATED/DELETED, LINK_CREATED/DELETED

- [ ] **3.7 Admin module**
  `core/src/modules/admin/`:
  - `services.py`:
    - `AdminService` — list_users(filters, pagination), update_user_role(id, role), update_user_status(id, status)
    - `SystemService` — get_stats() → {total_users, active_sessions, events_24h, db_size, redis_memory}
  - `routes.py`:
    - `GET /api/admin/users` — paginated user list (admin only)
    - `PATCH /api/admin/users/{id}` — update role/status
    - `GET /api/admin/stats` — system statistics
    - `GET /api/admin/events` — recent event log (from EventBus)
  - All routes: `require_permission("admin.*")`

- [ ] **3.8 Register all module routers**
  Update `core/src/main.py`:
  - Import and mount finance, quest, muse, admin routers
  - Register event handlers from each module
  - Register hook points from each module

- [ ] **3.9 Verify modules**
  - Each module's CRUD endpoints respond correctly
  - Events are emitted on create/update/delete
  - RBAC enforced (user can access finance, guest cannot write)
  - Pagination works (limit, offset, sort, filter)

---

## Track 4: `feat/web-complete`

**Branch**: `feat/web-complete`
**Worktree**: `../ws-web/`
**Scope**: `workbench/`, `libs/typescript/`
**Dependencies**: Needs T2 API contracts. Can build UI first with mock/type stubs.
**V1 Reference**: Frontend section of `v1-feature-inventory.md`

### Tasks

- [ ] **4.1 TypeScript shared lib — API client**
  `libs/typescript/src/api/`:
  - `client.ts` — `apiClient` with fetch wrapper: base URL, credentials: "include", error handling (parse ErrorResponse), type-safe generics
  - `types.ts` — `PaginatedResponse<T>`, `ErrorResponse`, `ApiError` class
  - `resource.ts` — `createResourceApi<T>(basePath)` → { list, get, create, update, delete }

- [ ] **4.2 TypeScript shared lib — Auth**
  `libs/typescript/src/auth/`:
  - `types.ts` — `User`, `AuthState`, `LoginRequest`, `RegisterRequest`, `OAuthProvider`
  - `AuthProvider.tsx` — React context: user state, loading, initialized; actions: login, register, logout, checkSession, linkProvider
  - `AuthGuard.tsx` — Wraps routes, redirects to /login if unauthenticated
  - `useAuth.ts` — Hook consuming AuthProvider context

- [ ] **4.3 TypeScript shared lib — Components**
  `libs/typescript/src/components/`:
  - `DataTable.tsx` — Props: columns, data, sortable, pagination, onSort, onPageChange, loading, emptyMessage. Catppuccin Mocha styled.
  - `Modal.tsx` — Props: isOpen, onClose, title, children, footer. Backdrop click closes.
  - `Toast.tsx` — Toast manager: useToast() → { success, error, warning, info }. Auto-dismiss.
  - `LoadingSpinner.tsx` — Centered spinner with optional message
  - `EmptyState.tsx` — Icon + message + optional action button
  - `ErrorBoundary.tsx` — Catches React errors, shows fallback UI

- [ ] **4.4 TypeScript shared lib — Hooks**
  `libs/typescript/src/hooks/`:
  - `useResource.ts` — `createResourceHook<T>(api)` → { items, loading, error, create, update, remove, refresh }
  - `usePagination.ts` — page, pageSize, sort, filter state management
  - `useWebSocket.ts` — WebSocket with auto-reconnect + message handler

- [ ] **4.5 Auth module — Login page**
  `workbench/src/modules/auth/pages/LoginPage.tsx`:
  - Email + password form (validation, error display)
  - "Sign in with GitHub" button → `window.location = /auth/oauth/github`
  - "Sign in with Google" button → Google One Tap integration
  - "Sign in with Passkey" button → `@simplewebauthn/browser` startAuthentication
  - Link to register page
  - Responsive: full-width on mobile, centered card on desktop
  - Catppuccin Mocha dark theme

- [ ] **4.6 Auth module — Register page**
  `workbench/src/modules/auth/pages/RegisterPage.tsx`:
  - Name + email + password + confirm password
  - Password strength indicator
  - "Or register with" → GitHub, Google buttons
  - "Add Passkey" option after registration (optional step)
  - Link to login page

- [ ] **4.7 Auth module — Settings page**
  `workbench/src/modules/auth/pages/AccountSettings.tsx`:
  - Linked providers list (email, github, google, passkey)
  - "Link GitHub/Google" buttons
  - Passkey management (list credentials, add new, remove)
  - Active sessions list (with revoke)
  - Profile edit (display name, avatar)

- [ ] **4.8 Finance module**
  `workbench/src/modules/finance/`:
  - `api.ts` — `createResourceApi<Transaction>('/api/finance/transactions')` + summary API
  - `hooks.ts` — `useTransactions`, `useBudgets`, `useMonthlySummary`
  - `pages/Dashboard.tsx` — Summary cards (income/expense/balance), category donut chart, recent transactions
  - `pages/TransactionList.tsx` — DataTable with filters (type, category, date range), create button
  - `components/TransactionForm.tsx` — Modal form for create/edit
  - `components/BudgetCard.tsx` — Budget vs actual progress bar, alert on exceed
  - `types.ts` — Transaction, Budget, MonthlySummary types

- [ ] **4.9 Quest module**
  `workbench/src/modules/quest/`:
  - `api.ts` — Quest CRUD + accept/complete/fail actions
  - `hooks.ts` — `useQuests`, `useQuestBoard`, `useSkills`
  - `pages/QuestBoard.tsx` — Kanban columns: Available, In Progress, Completed. Drag-and-drop optional.
  - `pages/QuestDetail.tsx` — Quest info, progress, XP reward, action buttons
  - `components/QuestCard.tsx` — Card: title, difficulty badge, XP, status, deadline
  - `components/SkillTree.tsx` — Tree/graph visualization of skills + levels
  - `types.ts` — Quest, Progress, Skill types

- [ ] **4.10 Muse module**
  `workbench/src/modules/muse/`:
  - `api.ts` — Spark CRUD + search + link API
  - `hooks.ts` — `useSparks`, `useSparkSearch`, `useGraph`
  - `pages/Inbox.tsx` — List of recent/unlinked sparks, create button
  - `pages/SparkDetail.tsx` — Markdown editor/viewer, linked sparks sidebar
  - `components/SparkEditor.tsx` — Markdown textarea with preview
  - `components/LinkGraph.tsx` — Force-directed graph (canvas or SVG), nodes = sparks, edges = links
  - `types.ts` — Spark, Link, GraphData types

- [ ] **4.11 Admin module**
  `workbench/src/modules/admin/`:
  - `api.ts` — User management + system stats
  - `hooks.ts` — `useUsers`, `useSystemStats`
  - `pages/Dashboard.tsx` — System stats cards (users, sessions, events, db size), live feed
  - `pages/UserManagement.tsx` — DataTable of users, inline role/status edit
  - `components/UserRow.tsx` — Role dropdown, status toggle, last active
  - Route guard: admin role only (redirect non-admins)
  - `types.ts` — AdminUser, SystemStats types

- [ ] **4.12 Shell enhancements**
  `workbench/src/shell/`:
  - `NavBar.tsx` — User avatar dropdown (profile, settings, logout), notification bell placeholder
  - `Sidebar.tsx` — Active route highlighting, collapse on mobile (hamburger menu)
  - `Layout.tsx` — Bottom nav on mobile (<640px), sidebar on desktop
  - `AppLauncher.tsx` — Dynamic: show/hide apps based on user role + permissions
  - Install `@simplewebauthn/browser` for passkey support

- [ ] **4.13 App routing update**
  `workbench/src/App.tsx`:
  - Add routes: /account (settings), /finance/*, /quest/*, /muse/*, /admin/*
  - Auth routes: /login, /register (no guard)
  - Admin guard for /admin/*
  - 404 catch-all

- [ ] **4.14 PWA + Icons**
  - Generate proper PNG icons (192x192, 512x512) — not SVG placeholders
  - Update `manifest.json` with correct names
  - `sw.js` — cache versioning, update notification
  - Offline fallback page

- [ ] **4.15 Verify**
  - `pnpm build` passes
  - All routes navigable
  - Responsive at 320px, 768px, 1280px
  - Auth flow: login → dashboard → navigate modules → logout
  - No TypeScript errors, no console errors

---

## Merge Order & Integration

1. [ ] Merge `feat/infra-db` → main (DB schemas ready)
2. [ ] Merge `feat/core-engine` → main (rebase, resolve conflicts)
3. [ ] Merge `feat/domain-modules` → main (rebase, may need main.py merge)
4. [ ] Merge `feat/web-complete` → main (rebase, package.json merge)
5. [ ] Integration test:
   - `docker compose up -d` (PG + Redis + LGTM)
   - `uv run uvicorn core.main:app --port 8800`
   - `pnpm dev` (apps/web)
   - Register → Login → Navigate → CRUD → Logout
6. [ ] Tag `v2.0.0-alpha`
