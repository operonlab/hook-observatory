---
doc_version: 2
content_hash: 85d21b7c
source_hash: 5b2b5428
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# V2 Worktree 待辦事項列表 (修訂版)

> 這不是遷移。這是根據 V1 文件與 V2 架構，以最大化程式碼複用為目標，從頭開始重建所有功能。
> 參考文件：`v1-feature-inventory.md`（V1 功能清單），`v2-blueprint.md`（V2 設計）。

## 設定

```bash
# 從 ~/workshop/ (main 分支, 在 blueprint 提交之後)
git worktree add ../ws-infra    -b feat/infra-db
git worktree add ../ws-engine   -b feat/core-engine
git worktree add ../ws-modules  -b feat/domain-modules
git worktree add ../ws-web      -b feat/web-complete
```

**每個會話的重要事項**:
- 閱讀 `docs/blueprint/v2-blueprint.md` 以了解架構決策
- 閱讀 `docs/blueprint/v1-feature-inventory.md` 作為 V1 參考
- 使用 Sonnet agents (而非 Haiku)。不要使用外部 CLI (Codex/Gemini)。
- 每個軌道只能在指定的目錄中工作。

---

## 軌道 1: `feat/infra-db`

**分支**: `feat/infra-db`
**Worktree**: `../ws-infra/`
**範疇**: `infra/`, `docker-compose*.yml`, `core/migrations/`
**依賴**: 無

### 任務

- [ ] **1.1 Docker Compose 開發堆疊**
  建立 `docker-compose.dev.yml`:
  - PostgreSQL 16 (port 5432, user: workshop, db: workshop_dev)
  - Redis 7 (port 6379)
  - Grafana LGTM all-in-one `grafana/otel-lgtm` (ports: 3100 grafana, 4317 OTLP gRPC, 4318 OTLP HTTP)
  - 網路: `workshop-net`
  - 儲存卷: `pg-data`, `redis-data`
  - `.env.example` 包含所有變數

- [ ] **1.2 PostgreSQL 初始化 schemas**
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
  掛載為 `docker-entrypoint-initdb.d` volume.

- [ ] **1.3 認證(Auth)遷移 SQL**
  `core/migrations/001_auth.sql`:
  - `auth.users` (id UUID PK, email UNIQUE, display_name, avatar_url, role, status, timestamps)
  - `auth.local_credentials` (user_id FK PK, password_hash, email_verified)
  - `auth.oauth_accounts` (id, user_id FK, provider, provider_user_id, email, tokens, raw_profile JSONB, UNIQUE(provider, provider_user_id))
  - `auth.webauthn_credentials` (id, user_id FK, credential_id BYTEA UNIQUE, public_key BYTEA, sign_count, aaguid, transports, backup fields, device_name)
  - `auth.sessions` (id VARCHAR PK, user_id FK, ip_address INET, user_agent, expires_at, last_active_at)
  - 所有索引

- [ ] **1.4 財物(Finance)遷移 SQL**
  `core/migrations/002_finance.sql`:
  - `finance.transactions` (id, user_id, type enum, amount decimal, currency, category, description, date, tags[], created_at, updated_at)
  - `finance.budgets` (id, user_id, category, amount, period enum, start_date, created_at)
  - `finance.categories` (id, user_id, name, icon, color, type, sort_order)

- [ ] **1.5 任務(Quest)遷移 SQL**
  `core/migrations/003_quest.sql`:
  - `quest.quests` (id, creator_id, title, description, status enum, xp_reward, difficulty, tags[], deadline, created_at)
  - `quest.progress` (id, quest_id, user_id, status enum, started_at, completed_at)
  - `quest.skills` (id, user_id, name, category, xp_total, level)

- [ ] **1.6 靈感(Muse)遷移 SQL**
  `core/migrations/004_muse.sql`:
  - `muse.sparks` (id, user_id, type enum, title, content text, tags[], metadata JSONB, created_at, updated_at)
  - `muse.links` (id, source_id FK, target_id FK, relation varchar, strength float, created_at)

- [ ] **1.7 Redis 設定**
  `infra/docker/redis/redis.conf`:
  - maxmemory 256mb, allkeys-lru
  - 針對 EventBus 消費者群組的 Stream 設定文件

- [ ] **1.8 Nginx 反向代理**
  `infra/nginx/nginx.conf`:
  - 上游服務: core(:8800), realtime(:8830), media(:8831), web(:3000 dev)
  - 路由: /auth/*, /api/* → core; /ws/*, /rtc/* → realtime; / → web
  - 安全標頭 (X-Frame-Options, CSP, HSTS)
  - `infra/nginx/Dockerfile`

- [ ] **1.9 LGTM 可觀測性設定**
  `infra/observability/`:
  - `otel-collector.yml` — 接收器 (OTLP gRPC + HTTP), 匯出器 (Loki, Tempo, Prometheus)
  - `grafana/provisioning/dashboards/workshop-overview.json` — 基礎儀表板

- [ ] **1.10 開發腳本**
  `infra/scripts/dev-setup.sh`:
  - 檢查先決條件 (docker, uv, pnpm)
  - `docker compose -f docker-compose.dev.yml up -d`
  - 等待 PG 就緒 (`pg_isready`)
  - 執行遷移
  - `uv sync && pnpm install`
  - 印出服務 URLs

  `infra/scripts/dev-teardown.sh`:
  - `docker compose down [-v]`

- [ ] **1.11 驗證**
  - `docker compose up -d` → 所有服務健康
  - PG: `psql -c '\dn'` 顯示 5 個 schemas
  - PG: 所有資料表已建立且欄位正確
  - Redis: `redis-cli ping` → PONG
  - Grafana: http://localhost:3100 可載入

---

## 軌道 2: `feat/core-engine`

**分支**: `feat/core-engine`
**Worktree**: `../ws-engine/`
**範疇**: `libs/python/`, `core/src/` (events, hooks, middleware, modules/auth, shared, config, main, db)
**依賴**: 開始時無。需要 T1 以進行資料庫測試。
**V1 參考**: `v1-feature-inventory.md` 的 Auth 部分

### 任務

- [ ] **2.1 Python 共享函式庫 — 資料庫層**
  `libs/python/src/corelib/db/`:
  - `pool.py` — `create_pool(db_url) → AsyncConnectionPool` (psycopg 3 async), lifespan helpers
  - `migrations.py` — `MigrationRunner` — 讀取 `migrations/*.sql`, 在 `public.schema_migrations` 中追蹤, CLI 進入點

- [ ] **2.2 Python 共享函式庫 — 基礎類別**
  `libs/python/src/corelib/`:
  - `schemas.py` — `PaginatedResponse[T]`, `ErrorResponse`, `SortOrder`, `FilterOp`, `Pagination`
  - `repository.py` — `BaseRepository[T]` — 針對 psycopg pool 的通用非同步 CRUD, 支援分頁
  - `service.py` — `BaseService[T]` — 包裝 BaseRepository + 自動權限檢查 + 自動事件觸發
  - `router.py` — `create_crud_router()` — 從 service + schemas + 權限對應產生 GET (list), GET/{id}, POST, PUT/{id}, DELETE/{id}
  - `events.py` — `CRUDEventMixin` — 自動觸發 `{domain}.{entity}.{created|updated|deleted}`
  - `health.py` — `create_health_router(name, version, checks: list)` — /health + /health/ready
  - 更新 `libs/python/pyproject.toml` (依賴: psycopg[pool], pydantic, structlog)

- [ ] **2.3 Python 共享函式庫 — 認證(Auth)抽象**
  `libs/python/src/corelib/auth/`:
  - `provider.py` — `AuthProvider` ABC (`authenticate()`, `provider_name`)
  - `session.py` — `SessionManager` (建立、驗證、撤銷、依使用者列出; DB支援並具備TTL; 帶有 session ID 的簽名 cookie)
  - `deps.py` — `get_current_user(request)`, `require_role(*roles)`, `require_permission(perm)`
  - `types.py` — `AuthResult`, `UserIdentity`, `SessionPayload`

- [ ] **2.4 Python 共享函式庫 — 中介軟體**
  `libs/python/src/corelib/middleware/`:
  - `errors.py` — 全域例外處理器 → `{"error": str, "code": str, "detail": any, "trace_id": str}`
  - `logging.py` — structlog 設定 (JSON prod, console dev), 綁定 trace_id + user_id
  - `telemetry.py` — OTel FastAPI 儀表化, 針對 EventBus 的自訂 span
  - `rate_limit.py` — slowapi 包裝器, 每個路由的限制, Redis 後端支援

- [ ] **2.5 Core 設定更新**
  `core/src/config.py`:
  - 新增: `webauthn_rp_id`, `webauthn_rp_name`, `webauthn_origin`
  - 新增: `github_client_id`, `github_client_secret`
  - 新增: `google_client_id`, `google_client_secret`
  - 新增: `public_base_url` (用於 OAuth 重導向 URIs)
  - 新增: `session_secret` (用於 cookie 簽名)
  - 保留: db_url, redis_url, cors_origins, event_backend, plugin_dir

- [ ] **2.6 Core 資料庫整合**
  `core/src/db.py`:
  - 使用 `corelib.db.create_pool(settings.db_url)`
  - 整合至 FastAPI lifespan (啟動時開啟, 關閉時關閉)
  - FastAPI 依賴: `get_pool()`, `get_conn()`

- [ ] **2.7 認證模組 — Email/Password 提供者**
  `core/src/modules/auth/providers/email.py`:
  - `EmailPasswordProvider(AuthProvider)`
  - 註冊: 驗證 email + password(>=8) → bcrypt hash → 建立 user + local_credentials
  - 登入: 驗證 email + bcrypt → 回傳 AuthResult
  - 使用 passlib CryptContext(schemes=["bcrypt"])

- [ ] **2.8 認證模組 — GitHub OAuth 提供者**
  `core/src/modules/auth/providers/github.py`:
  - `GitHubOAuthProvider(AuthProvider)`
  - 使用 authlib: 註冊 github oauth, authorize_redirect, authorize_access_token
  - 取得 /user + /user/emails (主要的已驗證 email)
  - 回傳 AuthResult，其中 provider_user_id = github user id
  - 支援白名單 (可選的環境變數)

- [ ] **2.9 認證模組 — Google OAuth 提供者**
  `core/src/modules/auth/providers/google.py`:
  - `GoogleOAuthProvider(AuthProvider)`
  - 使用 authlib: OIDC discovery, authorize_redirect, authorize_access_token
  - 啟用 PKCE (code_challenge_method: S256)
  - 從 ID token 中提取 userinfo
  - Google One Tap: POST 端點, 使用 google-auth 函式庫驗證
  - 回傳 AuthResult，其中 provider_user_id = sub claim

- [ ] **2.10 認證模組 — Passkey 提供者**
  `core/src/modules/auth/providers/passkey.py`:
  - `PasskeyProvider(AuthProvider)`
  - 使用 py_webauthn (webauthn>=2.7.1)
  - 註冊: generate_registration_options → verify_registration_response → 儲存憑證 (BYTEA)
  - 認證: generate_authentication_options → verify_authentication_response → 更新 sign_count
  - 憑證管理: 列出, 刪除

- [ ] **2.11 認證模組 — Service + Routes**
  `core/src/modules/auth/`:
  - `service.py` — `AuthService` 協調器: authenticate(provider, **kwargs), link_account(), create_session(), revoke_session()
  - 帳號連結: 檢查 provider_user_id → 檢查 email → 建立新使用者
  - `routes.py` — 所有藍圖中的端點 (註冊, 登入, 登出, session, OAuth 流程, Passkey 流程, 提供者管理)
  - `repository.py` — `UserRepository`, `OAuthAccountRepository`, `WebAuthnCredentialRepository`, `SessionRepository`
  - `schemas.py` — 所有端點的請求/回應 Pydantic 模型

- [ ] **2.12 認證模組 — RBAC + ABAC**
  重寫 `core/src/modules/auth/permissions.py`:
  - 保留 ROLE_PERMISSIONS dict (admin, user, guest)
  - 保留 PolicyEngine 與 RequestContext
  - 與 corelib deps 整合: `require_permission()` 自動檢查 RBAC + ABAC
  - 新增策略: suspended_users_blocked, owner_only_write, rate_limited

- [ ] **2.13 EventBus — Redis Streams 後端**
  `core/src/events/backends/`:
  - `memory.py` — 提取目前的進程內實作
  - `redis_streams.py` — XADD, XREADGROUP, 每個模組的消費者群組
  - `core/src/events/bus.py` — 透過 settings.event_backend 選擇後端

- [ ] **2.14 Core main.py 更新**
  - 串接: db pool, 所有 auth providers, auth service, session middleware
  - 新增: Starlette SessionMiddleware (用於 OAuth state)
  - 新增: OTel middleware, 結構化日誌, 全域錯誤處理器, 速率限制
  - 掛載: auth router, health router
  - Lifespan: db pool open/close, event_bus start/stop, hook_bus load_plugins

- [ ] **2.15 驗證完整認證流程**
  - 透過 email/password 註冊 → session 建立 → /auth/session 回傳 user
  - 登入 → session → 登出 → session 被撤銷
  - OAuth 流程 (mock 或使用真實金鑰)
  - Passkey 註冊 + 認證 (使用 Chrome 測試)
  - RBAC: admin 可以存取 admin 路由, user 不行
  - 速率限制: 1 分鐘內第 6 次登入嘗試 → 429

---

## 軌道 3: `feat/domain-modules`

**分支**: `feat/domain-modules`
**Worktree**: `../ws-modules/`
**範疇**: `core/src/modules/{finance,quest,muse,admin}/`
**依賴**: 需要 T2 基礎類別 (BaseService, BaseRepository, create_crud_router)。初期可以用 stub。
**策略**: 如果 T2 尚未合併，先在本地定義最小介面，待合併後再重構。

### 任務

- [ ] **3.1 財物模組 — Repository + Service**
  `core/src/modules/finance/`:
  - `repository.py`:
    - `TransactionRepo(BaseRepository[Transaction])` — schema="finance", table="transactions"
    - `BudgetRepo(BaseRepository[Budget])` — schema="finance", table="budgets"
    - `CategoryRepo(BaseRepository[Category])` — 自訂: 預設分類種子資料
  - `services.py`:
    - `TransactionService(BaseService[Transaction])` — domain="finance"
    - 自訂: `get_monthly_summary(user_id, year, month)`, `get_by_category(user_id, category)`
    - `BudgetService(BaseService[Budget])` — 自訂: `check_budget_alert(user_id, category)`

- [ ] **3.2 財物模組 — Routes + Schemas**
  - `schemas.py`:
    - `TransactionCreate` (type: income|expense, amount: Decimal, currency, category, description, date, tags)
    - `TransactionUpdate` (所有欄位可選)
    - `TransactionResponse` (id, + 所有欄位 + created_at)
    - `TransactionFilter` (type, category, date_from, date_to, amount_min, amount_max)
    - `MonthlySummary` (income, expense, balance, by_category: list)
    - 對 Budget, Category 使用相同模式
  - `routes.py`:
    - 透過 `create_crud_router("/api/finance/transactions", ...)` 建立 CRUD，權限: finance.read/write
    - 自訂: `GET /api/finance/summary?year=&month=` → MonthlySummary
    - budgets, categories 的 CRUD
  - `events.py`:
    - 常數: `TRANSACTION_CREATED/UPDATED/DELETED`, `BUDGET_CREATED/EXCEEDED`
    - 處理器: on transaction_created → 檢查預算 → 若超支則觸發 budget_exceeded

- [ ] **3.3 任務模組 — Repository + Service**
  `core/src/modules/quest/`:
  - `repository.py`:
    - `QuestRepo(BaseRepository[Quest])` — schema="quest", table="quests"
    - `ProgressRepo(BaseRepository[Progress])` — schema="quest", table="progress"
    - `SkillRepo(BaseRepository[Skill])` — schema="quest", table="skills"
  - `services.py`:
    - `QuestService(BaseService[Quest])` — domain="quest"
    - 自訂: `accept(quest_id, user_id)`, `complete(quest_id, user_id)`, `fail(quest_id, user_id)`
    - XP 計算: on complete → 更新技能 XP → 重新計算等級
    - `SkillService` — `get_skill_tree(user_id)`, `add_xp(user_id, skill_name, amount)`

- [ ] **3.4 任務模組 — Routes + Schemas**
  - `schemas.py`: QuestCreate, QuestResponse, QuestFilter, ProgressResponse, SkillResponse, SkillTree
  - `routes.py`:
    - CRUD 任務: `/api/quest/quests` (權限: quest.read/write)
    - 動作: `POST /api/quest/quests/{id}/accept`, `/complete`, `/fail`
    - 技能: `GET /api/quest/skills` (使用者的技能樹), `GET /api/quest/skills/{id}`
    - 任務板: `GET /api/quest/board` (依狀態分組)
  - `events.py`: QUEST_CREATED/ACCEPTED/COMPLETED/FAILED, SKILL_XP_GAINED/LEVEL_UP

- [ ] **3.5 靈感模組 — Repository + Service**
  `core/src/modules/muse/`:
  - `repository.py`:
    - `SparkRepo(BaseRepository[Spark])` — 自訂: 在 title+content 上全文搜尋, 標籤過濾
    - `LinkRepo(BaseRepository[Link])` — 自訂: get_graph(user_id), get_connected(spark_id)
  - `services.py`:
    - `SparkService(BaseService[Spark])` — domain="muse"
    - 自訂: `search(user_id, query, tags)`, `get_inbox(user_id)` (最近未連結的靈感)
    - `LinkService` — `link(source_id, target_id, relation)`, `unlink(link_id)`, `get_graph(user_id)`

- [ ] **3.6 靈感模組 — Routes + Schemas**
  - `schemas.py`: SparkCreate, SparkResponse, SparkFilter, LinkCreate, LinkResponse, GraphResponse
  - `routes.py`:
    - CRUD 靈感: `/api/muse/sparks` (權限: muse.read/write)
    - 搜尋: `GET /api/muse/sparks/search?q=&tags=`
    - 收件匣: `GET /api/muse/sparks/inbox`
    - 連結: `POST /api/muse/links`, `DELETE /api/muse/links/{id}`
    - 圖譜: `GET /api/muse/graph`
  - `events.py`: SPARK_CREATED/UPDATED/DELETED, LINK_CREATED/DELETED

- [ ] **3.7 管理員模組**
  `core/src/modules/admin/`:
  - `services.py`:
    - `AdminService` — list_users(filters, pagination), update_user_role(id, role), update_user_status(id, status)
    - `SystemService` — get_stats() → {total_users, active_sessions, events_24h, db_size, redis_memory}
  - `routes.py`:
    - `GET /api/admin/users` — 分頁的使用者列表 (僅 admin)
    - `PATCH /api/admin/users/{id}` — 更新角色/狀態
    - `GET /api/admin/stats` — 系統統計
    - `GET /api/admin/events` — 最近的事件日誌 (從 EventBus)
  - 所有路由: `require_permission("admin.*")`

- [ ] **3.8 註冊所有模組路由**
  更新 `core/src/main.py`:
  - 匯入並掛載 finance, quest, muse, admin routers
  - 註冊每個模組的事件處理器
  - 註冊每個模組的掛鉤點

- [ ] **3.9 驗證模組**
  - 每個模組的 CRUD 端點回應正確
  - 建立/更新/刪除時觸發事件
  - RBAC 強制執行 (user 可存取 finance, guest 無法寫入)
  - 分頁功能正常 (limit, offset, sort, filter)

---

## 軌道 4: `feat/web-complete`

**分支**: `feat/web-complete`
**Worktree**: `../ws-web/`
**範疇**: `workbench/`, `libs/typescript/`
**依賴**: 需要 T2 API 合約。可先用 mock/type stubs 建立 UI。
**V1 參考**: `v1-feature-inventory.md` 的 Frontend 部分

### 任務

- [ ] **4.1 TypeScript 共享函式庫 — API 客戶端**
  `libs/typescript/src/api/`:
  - `client.ts` — `apiClient` 與 fetch 包裝器: base URL, credentials: "include", 錯誤處理 (解析 ErrorResponse), 型別安全的泛型
  - `types.ts` — `PaginatedResponse<T>`, `ErrorResponse`, `ApiError` class
  - `resource.ts` — `createResourceApi<T>(basePath)` → { list, get, create, update, delete }

- [ ] **4.2 TypeScript 共享函式庫 — 認證(Auth)**
  `libs/typescript/src/auth/`:
  - `types.ts` — `User`, `AuthState`, `LoginRequest`, `RegisterRequest`, `OAuthProvider`
  - `AuthProvider.tsx` — React context: user state, loading, initialized; actions: login, register, logout, checkSession, linkProvider
  - `AuthGuard.tsx` — 包裝路由, 未驗證則重導向至 /login
  - `useAuth.ts` — 使用 AuthProvider context 的 Hook

- [ ] **4.3 TypeScript 共享函式庫 — 元件**
  `libs/typescript/src/components/`:
  - `DataTable.tsx` — Props: columns, data, sortable, pagination, onSort, onPageChange, loading, emptyMessage. Catppuccin Mocha 風格。
  - `Modal.tsx` — Props: isOpen, onClose, title, children, footer. 點擊背景可關閉。
  - `Toast.tsx` — Toast 管理器: useToast() → { success, error, warning, info }. 自動關閉。
  - `LoadingSpinner.tsx` — 置中的 spinner，可選訊息
  - `EmptyState.tsx` — 圖示 + 訊息 + 可選的動作按鈕
  - `ErrorBoundary.tsx` — 捕捉 React 錯誤, 顯示備用 UI

- [ ] **4.4 TypeScript 共享函式庫 — Hooks**
  `libs/typescript/src/hooks/`:
  - `useResource.ts` — `createResourceHook<T>(api)` → { items, loading, error, create, update, remove, refresh }
  - `usePagination.ts` — page, pageSize, sort, filter 狀態管理
  - `useWebSocket.ts` — 具備自動重連 + 訊息處理器的 WebSocket

- [ ] **4.5 認證模組 — 登入頁面**
  `workbench/src/modules/auth/pages/LoginPage.tsx`:
  - Email + password 表單 (驗證, 錯誤顯示)
  - "Sign in with GitHub" 按鈕 → `window.location = /auth/oauth/github`
  - "Sign in with Google" 按鈕 → Google One Tap 整合
  - "Sign in with Passkey" 按鈕 → `@simplewebauthn/browser` startAuthentication
  - 前往註冊頁的連結
  - 響應式: 行動裝置上全寬, 桌面上置中卡片
  - Catppuccin Mocha 深色主題

- [ ] **4.6 認證模組 — 註冊頁面**
  `workbench/src/modules/auth/pages/RegisterPage.tsx`:
  - Name + email + password + confirm password
  - 密碼強度指示器
  - "Or register with" → GitHub, Google 按鈕
  - 註冊後可選 "Add Passkey"
  - 前往登入頁的連結

- [ ] **4.7 認證模組 — 設定頁面**
  `workbench/src/modules/auth/pages/AccountSettings.tsx`:
  - 已連結的提供者列表 (email, github, google, passkey)
  - "Link GitHub/Google" 按鈕
  - Passkey 管理 (列出憑證, 新增, 移除)
  - 活動中會話列表 (可撤銷)
  - 個人資料編輯 (顯示名稱, 頭像)

- [ ] **4.8 財物模組**
  `workbench/src/modules/finance/`:
  - `api.ts` — `createResourceApi<Transaction>('/api/finance/transactions')` + summary API
  - `hooks.ts` — `useTransactions`, `useBudgets`, `useMonthlySummary`
  - `pages/Dashboard.tsx` — 摘要卡片 (收入/支出/餘額), 分類圓餅圖, 最近交易
  - `pages/TransactionList.tsx` — 帶有過濾器 (類型, 分類, 日期範圍) 的 DataTable, 建立按鈕
  - `components/TransactionForm.tsx` — 用於建立/編輯的 Modal 表單
  - `components/BudgetCard.tsx` — 預算 vs 實際進度條, 超出時警示
  - `types.ts` — Transaction, Budget, MonthlySummary 型別

- [ ] **4.9 任務模組**
  `workbench/src/modules/quest/`:
  - `api.ts` — Quest CRUD + accept/complete/fail 動作
  - `hooks.ts` — `useQuests`, `useQuestBoard`, `useSkills`
  - `pages/QuestBoard.tsx` — Kanban 欄位: Available, In Progress, Completed. 可選的拖放功能。
  - `pages/QuestDetail.tsx` — 任務資訊, 進度, XP 獎勵, 動作按鈕
  - `components/QuestCard.tsx` — 卡片: 標題, 難度徽章, XP, 狀態, 截止日期
  - `components/SkillTree.tsx` — 技能與等級的樹狀/圖形視覺化
  - `types.ts` — Quest, Progress, Skill 型別

- [ ] **4.10 靈感模組**
  `workbench/src/modules/muse/`:
  - `api.ts` — Spark CRUD + search + link API
  - `hooks.ts` — `useSparks`, `useSparkSearch`, `useGraph`
  - `pages/Inbox.tsx` — 最近/未連結的靈感列表, 建立按鈕
  - `pages/SparkDetail.tsx` — Markdown 編輯器/檢視器, 連結的靈感側邊欄
  - `components/SparkEditor.tsx` — 帶有預覽的 Markdown 文字區
  - `components/LinkGraph.tsx` — 力導向圖 (canvas 或 SVG), 節點 = sparks, 邊 = links
  - `types.ts` — Spark, Link, GraphData 型別

- [ ] **4.11 管理員模組**
  `workbench/src/modules/admin/`:
  - `api.ts` — 使用者管理 + 系統統計
  - `hooks.ts` — `useUsers`, `useSystemStats`
  - `pages/Dashboard.tsx` — 系統統計卡片 (使用者, 會話, 事件, db 大小), 即時資訊流
  - `pages/UserManagement.tsx` — 使用者的 DataTable, 行內編輯角色/狀態
  - `components/UserRow.tsx` — 角色下拉選單, 狀態切換, 最後活動時間
  - 路由守衛: 僅 admin 角色 (重導向非 admin)
  - `types.ts` — AdminUser, SystemStats 型別

- [ ] **4.12 外殼增強**
  `workbench/src/shell/`:
  - `NavBar.tsx` — 使用者頭像下拉選單 (個人資料, 設定, 登出), 通知鈴鐺佔位符
  - `Sidebar.tsx` — 當前路由高亮, 行動裝置上摺疊 (漢堡選單)
  - `Layout.tsx` — 行動裝置(<640px)底部導覽, 桌面上側邊欄
  - `AppLauncher.tsx` — 動態: 根據使用者角色 + 權限顯示/隱藏應用程式
  - 安裝 `@simplewebauthn/browser` 以支援 passkey

- [ ] **4.13 App 路由更新**
  `workbench/src/App.tsx`:
  - 新增路由: /account (settings), /finance/*, /quest/*, /muse/*, /admin/*
  - 認證路由: /login, /register (無守衛)
  - /admin/* 的管理員守衛
  - 404 catch-all

- [ ] **4.14 PWA + 圖示**
  - 產生合適的 PNG 圖示 (192x192, 512x512) — 而非 SVG 佔位符
  - 更新 `manifest.json` 為正確名稱
  - `sw.js` — 快取版本控制, 更新通知
  - 離線備用頁面

- [ ] **4.15 驗證**
  - `pnpm build` 通過
  - 所有路由皆可導航
  - 在 320px, 768px, 1280px 下響應式
  - 認證流程: login → workbench → navigate modules → logout
  - 無 TypeScript 錯誤, 無 console 錯誤

---

## 合併順序與整合

1. [ ] 合併 `feat/infra-db` → main (DB schemas 就緒)
2. [ ] 合併 `feat/core-engine` → main (rebase, 解決衝突)
3. [ ] 合併 `feat/domain-modules` → main (rebase, 可能需要合併 main.py)
4. [ ] 合併 `feat/web-complete` → main (rebase, 合併 package.json)
5. [ ] 整合測試:
   - `docker compose up -d` (PG + Redis + LGTM)
   - `uv run uvicorn core.main:app --port 8800`
   - `pnpm dev` (apps/web)
   - 註冊 → 登入 → 導航 → CRUD → 登出
6. [ ] 標記 `v2.0.0-alpha`
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2472ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3130ms
