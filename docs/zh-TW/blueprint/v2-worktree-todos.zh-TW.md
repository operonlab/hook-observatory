---
doc_version: 2
content_hash: 85d21b7c
source_version: 2
translated_at: 2026-02-23
---

# V2 Worktree 待辦清單 (修訂版)

> 非遷移作業。從 V1 文件與 V2 架構重新建構所有內容，並最大限度地重複使用程式碼。
> 參考：`v1-feature-inventory.md` 用於 V1 功能，`v2-blueprint.md` 用於 V2 設計。

## 設定

```bash
# 於 ~/workshop/ (main 分支，在藍圖提交之後)
git worktree add ../ws-infra    -b feat/infra-db
git worktree add ../ws-engine   -b feat/core-engine
git worktree add ../ws-modules  -b feat/domain-modules
git worktree add ../ws-web      -b feat/web-complete
```

**每節工作階段重要事項**：
- 閱讀 `docs/blueprint/v2-blueprint.md` 以了解架構決策
- 閱讀 `docs/blueprint/v1-feature-inventory.md` 以獲取 V1 參考
- 使用 Sonnet 代理人 (非 Haiku)。請勿使用外部 CLI (Codex/Gemini)。
- 每個軌道僅在其指定的目錄中工作。

---

## 軌道 1：`feat/infra-db`

**分支**：`feat/infra-db`
**Worktree**：`../ws-infra/`
**範圍**：`infra/`, `docker-compose*.yml`, `core/migrations/`
**依賴關係**：無

### 任務

- [ ] **1.1 Docker Compose 開發堆疊**
  建立 `docker-compose.dev.yml`：
  - PostgreSQL 16 (連接埠 5432, 使用者: workshop, 資料庫: workshop_dev)
  - Redis 7 (連接埠 6379)
  - Grafana LGTM all-in-one `grafana/otel-lgtm` (連接埠：3100 grafana, 4317 OTLP gRPC, 4318 OTLP HTTP)
  - 網路：`workshop-net`
  - 磁碟卷：`pg-data`, `redis-data`
  - 包含所有變數的 `.env.example`

- [ ] **1.2 PostgreSQL 初始化結構 (Schemas)**
  `infra/docker/postgres/init.sql`：
  ```sql
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
  CREATE EXTENSION IF NOT EXISTS "pgcrypto";
  CREATE SCHEMA IF NOT EXISTS auth;
  CREATE SCHEMA IF NOT EXISTS finance;
  CREATE SCHEMA IF NOT EXISTS quest;
  CREATE SCHEMA IF NOT EXISTS muse;
  CREATE SCHEMA IF NOT EXISTS admin;
  ```
  掛載為 `docker-entrypoint-initdb.d` 磁碟卷。

- [ ] **1.3 Auth 遷移 SQL**
  `core/migrations/001_auth.sql`：
  - `auth.users` (id UUID PK, email UNIQUE, display_name, avatar_url, role, status, timestamps)
  - `auth.local_credentials` (user_id FK PK, password_hash, email_verified)
  - `auth.oauth_accounts` (id, user_id FK, provider, provider_user_id, email, tokens, raw_profile JSONB, UNIQUE(provider, provider_user_id))
  - `auth.webauthn_credentials` (id, user_id FK, credential_id BYTEA UNIQUE, public_key BYTEA, sign_count, aaguid, transports, backup fields, device_name)
  - `auth.sessions` (id VARCHAR PK, user_id FK, ip_address INET, user_agent, expires_at, last_active_at)
  - 所有索引

- [ ] **1.4 Finance 遷移 SQL**
  `core/migrations/002_finance.sql`：
  - `finance.transactions` (id, user_id, type enum, amount decimal, currency, category, description, date, tags[], created_at, updated_at)
  - `finance.budgets` (id, user_id, category, amount, period enum, start_date, created_at)
  - `finance.categories` (id, user_id, name, icon, color, type, sort_order)

- [ ] **1.5 Quest 遷移 SQL**
  `core/migrations/003_quest.sql`：
  - `quest.quests` (id, creator_id, title, description, status enum, xp_reward, difficulty, tags[], deadline, created_at)
  - `quest.progress` (id, quest_id, user_id, status enum, started_at, completed_at)
  - `quest.skills` (id, user_id, name, category, xp_total, level)

- [ ] **1.6 Muse 遷移 SQL**
  `core/migrations/004_muse.sql`：
  - `muse.sparks` (id, user_id, type enum, title, content text, tags[], metadata JSONB, created_at, updated_at)
  - `muse.links` (id, source_id FK, target_id FK, relation varchar, strength float, created_at)

- [ ] **1.7 Redis 配置**
  `infra/docker/redis/redis.conf`：
  - maxmemory 256mb, allkeys-lru
  - 用於 EventBus 消費者群組 (consumer groups) 的 Stream 配置文件

- [ ] **1.8 Nginx 反向代理**
  `infra/nginx/nginx.conf`：
  - Upstream: core(:8800), realtime(:8830), media(:8831), web(:3000 dev)
  - Routes: /auth/*, /api/* → core; /ws/*, /rtc/* → realtime; / → web
  - 安全性標頭 (X-Frame-Options, CSP, HSTS)
  - `infra/nginx/Dockerfile`

- [ ] **1.9 LGTM 可觀測性配置**
  `infra/observability/`：
  - `otel-collector.yml` — 接收器 (OTLP gRPC + HTTP), 匯出器 (Loki, Tempo, Prometheus)
  - `grafana/provisioning/dashboards/workshop-overview.json` — 基礎儀表板

- [ ] **1.10 開發腳本**
  `infra/scripts/dev-setup.sh`：
  - 檢查前置條件 (docker, uv, pnpm)
  - `docker compose -f docker-compose.dev.yml up -d`
  - 等待 PG 就緒 (`pg_isready`)
  - 執行遷移
  - `uv sync && pnpm install`
  - 列印服務 URL

  `infra/scripts/dev-teardown.sh`：
  - `docker compose down [-v]`

- [ ] **1.11 驗證**
  - `docker compose up -d` → 所有服務健康狀況良好
  - PG: `psql -c '\dn'` 顯示 5 個 schemas
  - PG: 所有資料表已建立且欄位正確
  - Redis: `redis-cli ping` → PONG
  - Grafana: http://localhost:3100 載入成功

---

## 軌道 2：`feat/core-engine`

**分支**：`feat/core-engine`
**Worktree**：`../ws-engine/`
**範圍**：`libs/python/`, `core/src/` (events, hooks, middleware, modules/auth, shared, config, main, db)
**依賴關係**：無。需要 T1 以進行資料庫測試。
**V1 參考**：`v1-feature-inventory.md` 中的 Auth 章節

### 任務

- [ ] **2.1 Python 共用函式庫 — 資料庫層**
  `libs/python/src/corelib/db/`：
  - `pool.py` — `create_pool(db_url) → AsyncConnectionPool` (psycopg 3 async), lifespan 輔助工具
  - `migrations.py` — `MigrationRunner` — 讀取 `migrations/*.sql`，在 `public.schema_migrations` 中追蹤，CLI 入口

- [ ] **2.2 Python 共用函式庫 — 基礎類別**
  `libs/python/src/corelib/`：
  - `schemas.py` — `PaginatedResponse[T]`, `ErrorResponse`, `SortOrder`, `FilterOp`, `Pagination`
  - `repository.py` — `BaseRepository[T]` — 針對 psycopg 連接池的泛型非同步 CRUD，支援分頁
  - `service.py` — `BaseService[T]` — 封裝 BaseRepository + 自動權限檢查 + 自動事件發送
  - `router.py` — `create_crud_router()` — 從 service + schemas + 權限映射產生 GET (列表), GET/{id}, POST, PUT/{id}, DELETE/{id}
  - `events.py` — `CRUDEventMixin` — 自動發送 `{domain}.{entity}.{created|updated|deleted}`
  - `health.py` — `create_health_router(name, version, checks: list)` — /health + /health/ready
  - 更新 `libs/python/pyproject.toml` (依賴：psycopg[pool], pydantic, structlog)

- [ ] **2.3 Python 共用函式庫 — 認證抽象**
  `libs/python/src/corelib/auth/`：
  - `provider.py` — `AuthProvider` ABC (`authenticate()`, `provider_name`)
  - `session.py` — `SessionManager` (建立、驗證、撤銷、按使用者列出；DB 支援且具 TTL；帶有 session ID 的簽署 cookie)
  - `deps.py` — `get_current_user(request)`, `require_role(*roles)`, `require_permission(perm)`
  - `types.py` — `AuthResult`, `UserIdentity`, `SessionPayload`

- [ ] **2.4 Python 共用函式庫 — 中間件**
  `libs/python/src/corelib/middleware/`：
  - `errors.py` — 全域異常處理器 → `{"error": str, "code": str, "detail": any, "trace_id": str}`
  - `logging.py` — structlog 配置 (正式環境為 JSON，開發環境為控制台)，綁定 trace_id + user_id
  - `telemetry.py` — OTel FastAPI 儀器化，針對 EventBus 的自定義 spans
  - `rate_limit.py` — slowapi 封裝，每條路由限制，支援 Redis 後端

- [ ] **2.5 Core 配置更新**
  `core/src/config.py`：
  - 新增：`webauthn_rp_id`, `webauthn_rp_name`, `webauthn_origin`
  - 新增：`github_client_id`, `github_client_secret`
  - 新增：`google_client_id`, `google_client_secret`
  - 新增：`public_base_url` (用於 OAuth 重新導向 URI)
  - 新增：`session_secret` (用於 cookie 簽署)
  - 保留：db_url, redis_url, cors_origins, event_backend, plugin_dir

- [ ] **2.6 Core 資料庫整合**
  `core/src/db.py`：
  - 使用 `corelib.db.create_pool(settings.db_url)`
  - 整合進 FastAPI 生命週期 (啟動時開啟，關閉時關閉)
  - FastAPI 依賴項：`get_pool()`, `get_conn()`

- [ ] **2.7 Auth 模組 — Email/密碼提供者**
  `core/src/modules/auth/providers/email.py`：
  - `EmailPasswordProvider(AuthProvider)`
  - 註冊：驗證 email + 密碼(>=8) → bcrypt 雜湊 → 建立使用者 + local_credentials
  - 登入：驗證 email + bcrypt → 回傳 AuthResult
  - 使用 passlib CryptContext(schemes=["bcrypt"])

- [ ] **2.8 Auth 模組 — GitHub OAuth 提供者**
  `core/src/modules/auth/providers/github.py`：
  - `GitHubOAuthProvider(AuthProvider)`
  - 使用 authlib：註冊 github oauth, authorize_redirect, authorize_access_token
  - 獲取 /user + /user/emails (主要已驗證的 email)
  - 回傳 AuthResult，其中 provider_user_id = github user id
  - 白名單支援 (選填環境變數)

- [ ] **2.9 Auth 模組 — Google OAuth 提供者**
  `core/src/modules/auth/providers/google.py`：
  - `GoogleOAuthProvider(AuthProvider)`
  - 使用 authlib：OIDC 發現, authorize_redirect, authorize_access_token
  - 啟用 PKCE (code_challenge_method: S256)
  - 從 ID 權杖 (token) 中提取使用者資訊
  - Google One Tap：POST 端點，使用 google-auth 函式庫驗證
  - 回傳 AuthResult，其中 provider_user_id = sub claim

- [ ] **2.10 Auth 模組 — Passkey 提供者**
  `core/src/modules/auth/providers/passkey.py`：
  - `PasskeyProvider(AuthProvider)`
  - 使用 py_webauthn (webauthn>=2.7.1)
  - 註冊：generate_registration_options → verify_registration_response → 儲存憑證 (BYTEA)
  - 身份驗證：generate_authentication_options → verify_authentication_response → 更新 sign_count
  - 憑證管理：列出、刪除

- [ ] **2.11 Auth 模組 — 服務與路由**
  `core/src/modules/auth/`：
  - `service.py` — `AuthService` 協調器：authenticate(provider, **kwargs), link_account(), create_session(), revoke_session()
  - 帳號連結：檢查 provider_user_id → 檢查 email → 建立新使用者
  - `routes.py` — 藍圖中的所有端點 (註冊、登入、登出、工作階段、OAuth 流程、Passkey 流程、提供者管理)
  - `repository.py` — `UserRepository`, `OAuthAccountRepository`, `WebAuthnCredentialRepository`, `SessionRepository`
  - `schemas.py` — 所有端點的請求/回應 Pydantic 模型

- [ ] **2.12 Auth 模組 — RBAC + ABAC**
  改寫 `core/src/modules/auth/permissions.py`：
  - 保留 ROLE_PERMISSIONS 字典 (admin, user, guest)
  - 保留帶有 RequestContext 的 PolicyEngine
  - 與 corelib 依賴項整合：`require_permission()` 自動檢查 RBAC + ABAC
  - 新增政策：suspended_users_blocked, owner_only_write, rate_limited

- [ ] **2.13 EventBus — Redis Streams 後端**
  `core/src/events/backends/`：
  - `memory.py` — 提取目前的進程內 (in-process) 實作
  - `redis_streams.py` — XADD, XREADGROUP，每個模組的消費者群組
  - `core/src/events/bus.py` — 透過 settings.event_backend 選擇後端

- [ ] **2.14 Core main.py 更新**
  - 連接：資料庫連接池、所有認證提供者、認證服務、工作階段中間件
  - 新增：Starlette SessionMiddleware (用於 OAuth 狀態)
  - 新增：OTel 中間件、結構化日誌、全域錯誤處理器、速率限制
  - 掛載：auth 路由、健康檢查路由
  - 生命週期 (Lifespan)：資料庫連接池開啟/關閉、event_bus 啟動/停止、hook_bus 載入插件

- [ ] **2.15 驗證完整認證流程**
  - 透過 email/密碼註冊 → 建立工作階段 → /auth/session 回傳使用者
  - 登入 → 工作階段 → 登出 → 撤銷工作階段
  - OAuth 流程 (若有密鑰則使用真實流程，否則使用 mock)
  - Passkey 註冊與身份驗證 (使用 Chrome 測試)
  - RBAC：管理員可以存取管理員路由，一般使用者不行
  - 速率限制：1 分鐘內第 6 次登入嘗試 → 429

---

## 軌道 3：`feat/domain-modules`

**分支**：`feat/domain-modules`
**Worktree**：`../ws-modules/`
**範圍**：`core/src/modules/{finance,quest,muse,admin}/`
**依賴關係**：需要 T2 基礎類別 (BaseService, BaseRepository, create_crud_router)。初期可以使用 stub。
**策略**：如果 T2 尚未合併，請先在行內定義最小介面，並在合併時進行重構。

### 任務

- [ ] **3.1 Finance 模組 — Repository 與 Service**
  `core/src/modules/finance/`：
  - `repository.py`：
    - `TransactionRepo(BaseRepository[Transaction])` — schema="finance", table="transactions"
    - `BudgetRepo(BaseRepository[Budget])` — schema="finance", table="budgets"
    - `CategoryRepo(BaseRepository[Category])` — 自定義：預設類別種子資料 (seeding)
  - `services.py`：
    - `TransactionService(BaseService[Transaction])` — domain="finance"
    - 自定義：`get_monthly_summary(user_id, year, month)`, `get_by_category(user_id, category)`
    - `BudgetService(BaseService[Budget])` — 自定義：`check_budget_alert(user_id, category)`

- [ ] **3.2 Finance 模組 — 路由與 Schemas**
  - `schemas.py`：
    - `TransactionCreate` (type: income|expense, amount: Decimal, currency, category, description, date, tags)
    - `TransactionUpdate` (全部皆為選填)
    - `TransactionResponse` (id, + 所有欄位 + created_at)
    - `TransactionFilter` (type, category, date_from, date_to, amount_min, amount_max)
    - `MonthlySummary` (income, expense, balance, by_category: list)
    - Budget, Category 採用相同模式
  - `routes.py`：
    - 透過 `create_crud_router("/api/finance/transactions", ...)` 進行 CRUD，權限：finance.read/write
    - 自定義：`GET /api/finance/summary?year=&month=` → MonthlySummary
    - 預算、類別的 CRUD
  - `events.py`：
    - 常數：`TRANSACTION_CREATED/UPDATED/DELETED`, `BUDGET_CREATED/EXCEEDED`
    - 處理器：在 transaction_created 時 → 檢查預算 → 若超出則發送 budget_exceeded

- [ ] **3.3 Quest 模組 — Repository 與 Service**
  `core/src/modules/quest/`：
  - `repository.py`：
    - `QuestRepo(BaseRepository[Quest])` — schema="quest", table="quests"
    - `ProgressRepo(BaseRepository[Progress])` — schema="quest", table="progress"
    - `SkillRepo(BaseRepository[Skill])` — schema="quest", table="skills"
  - `services.py`：
    - `QuestService(BaseService[Quest])` — domain="quest"
    - 自定義：`accept(quest_id, user_id)`, `complete(quest_id, user_id)`, `fail(quest_id, user_id)`
    - XP 計算：完成時 → 更新技能 XP → 重新計算等級
    - `SkillService` — `get_skill_tree(user_id)`, `add_xp(user_id, skill_name, amount)`

- [ ] **3.4 Quest 模組 — 路由與 Schemas**
  - `schemas.py`：QuestCreate, QuestResponse, QuestFilter, ProgressResponse, SkillResponse, SkillTree
  - `routes.py`：
    - CRUD 任務：`/api/quest/quests` (權限：quest.read/write)
    - 動作：`POST /api/quest/quests/{id}/accept`, `/complete`, `/fail`
    - 技能：`GET /api/quest/skills` (使用者的技能樹), `GET /api/quest/skills/{id}`
    - 佈告欄：`GET /api/quest/board` (按狀態分組)
  - `events.py`：QUEST_CREATED/ACCEPTED/COMPLETED/FAILED, SKILL_XP_GAINED/LEVEL_UP

- [ ] **3.5 Muse 模組 — Repository 與 Service**
  `core/src/modules/muse/`：
  - `repository.py`：
    - `SparkRepo(BaseRepository[Spark])` — 自定義：針對標題與內容的全文檢索，標籤過濾
    - `LinkRepo(BaseRepository[Link])` — 自定義：get_graph(user_id), get_connected(spark_id)
  - `services.py`：
    - `SparkService(BaseService[Spark])` — domain="muse"
    - 自定義：`search(user_id, query, tags)`, `get_inbox(user_id)` (最近未連結的靈感 (sparks))
    - `LinkService` — `link(source_id, target_id, relation)`, `unlink(link_id)`, `get_graph(user_id)`

- [ ] **3.6 Muse 模組 — 路由與 Schemas**
  - `schemas.py`：SparkCreate, SparkResponse, SparkFilter, LinkCreate, LinkResponse, GraphResponse
  - `routes.py`：
    - CRUD 靈感：`/api/muse/sparks` (權限：muse.read/write)
    - 搜尋：`GET /api/muse/sparks/search?q=&tags=`
    - 收件匣：`GET /api/muse/sparks/inbox`
    - 連結：`POST /api/muse/links`, `DELETE /api/muse/links/{id}`
    - 圖譜：`GET /api/muse/graph`
  - `events.py`：SPARK_CREATED/UPDATED/DELETED, LINK_CREATED/DELETED

- [ ] **3.7 Admin 模組**
  `core/src/modules/admin/`：
  - `services.py`：
    - `AdminService` — list_users(過濾, 分頁), update_user_role(id, 角色), update_user_status(id, 狀態)
    - `SystemService` — get_stats() → {total_users, active_sessions, events_24h, db_size, redis_memory}
  - `routes.py`：
    - `GET /api/admin/users` — 分頁的使用者列表 (僅限管理員)
    - `PATCH /api/admin/users/{id}` — 更新角色/狀態
    - `GET /api/admin/stats` — 系統統計數據
    - `GET /api/admin/events` — 最近的事件日誌 (來自 EventBus)
  - 所有路由：`require_permission("admin.*")`

- [ ] **3.8 註冊所有模組路由**
  更新 `core/src/main.py`：
  - 匯入並掛載 finance, quest, muse, admin 路由
  - 註冊每個模組的事件處理器
  - 註冊每個模組的掛鉤點 (hook points)

- [ ] **3.9 驗證模組**
  - 每個模組的 CRUD 端點回應正確
  - 在建立/更新/刪除時發送事件
  - 強制執行 RBAC (一般使用者可存取 finance，訪客無法寫入)
  - 分頁功能正常 (limit, offset, sort, filter)

---

## 軌道 4：`feat/web-complete`

**分支**：`feat/web-complete`
**Worktree**：`../ws-web/`
**範圍**：`dashboard/`, `libs/typescript/`
**依賴關係**：需要 T2 API 合約。初期可以使用 mock/類型 stub 先建立 UI。
**V1 參考**：`v1-feature-inventory.md` 中的前端章節

### 任務

- [ ] **4.1 TypeScript 共用函式庫 — API 客戶端**
  `libs/typescript/src/api/`：
  - `client.ts` — 帶有 fetch 封裝的 apiClient：基礎 URL, credentials: "include", 錯誤處理 (解析 ErrorResponse), 類型安全泛型
  - `types.ts` — `PaginatedResponse<T>`, `ErrorResponse`, `ApiError` 類別
  - `resource.ts` — `createResourceApi<T>(basePath)` → { list, get, create, update, delete }

- [ ] **4.2 TypeScript 共用函式庫 — 認證**
  `libs/typescript/src/auth/`：
  - `types.ts` — `User`, `AuthState`, `LoginRequest`, `RegisterRequest`, `OAuthProvider`
  - `AuthProvider.tsx` — React context：使用者狀態、載入中、已初始化；動作：登入、註冊、登出、檢查工作階段、連結提供者
  - `AuthGuard.tsx` — 封裝路由，若未認證則導向 /login
  - `useAuth.ts` — 使用 AuthProvider context 的 Hook

- [ ] **4.3 TypeScript 共用函式庫 — 元件**
  `libs/typescript/src/components/`：
  - `DataTable.tsx` — Props: columns, data, sortable, pagination, onSort, onPageChange, loading, emptyMessage。採用 Catppuccin Mocha 風格。
  - `Modal.tsx` — Props: isOpen, onClose, title, children, footer。點擊背景關閉。
  - `Toast.tsx` — Toast 管理器：useToast() → { success, error, warning, info }。自動關閉。
  - `LoadingSpinner.tsx` — 置中讀取圖示，可選帶有訊息
  - `EmptyState.tsx` — 圖示 + 訊息 + 可選動作按鈕
  - `ErrorBoundary.tsx` — 捕捉 React 錯誤，顯示備用 UI

- [ ] **4.4 TypeScript 共用函式庫 — Hooks**
  `libs/typescript/src/hooks/`：
  - `useResource.ts` — `createResourceHook<T>(api)` → { items, loading, error, create, update, remove, refresh }
  - `usePagination.ts` — page, pageSize, sort, filter 狀態管理
  - `useWebSocket.ts` — 帶有自動重連與訊息處理器的 WebSocket

- [ ] **4.5 Auth 模組 — 登入頁面**
  `dashboard/src/modules/auth/pages/LoginPage.tsx`：
  - Email + 密碼表單 (驗證、錯誤顯示)
  - "Sign in with GitHub" 按鈕 → `window.location = /auth/oauth/github`
  - "Sign in with Google" 按鈕 → Google One Tap 整合
  - "Sign in with Passkey" 按鈕 → ` @simplewebauthn/browser` startAuthentication
  - 連結至註冊頁面
  - 響應式：手機上為全寬，桌機上為置中卡片
  - Catppuccin Mocha 深色主題

- [ ] **4.6 Auth 模組 — 註冊頁面**
  `dashboard/src/modules/auth/pages/RegisterPage.tsx`：
  - 姓名 + email + 密碼 + 確認密碼
  - 密碼強度指示器
  - "Or register with" → GitHub, Google 按鈕
  - 註冊後提供「新增 Passkey」選項 (選填步驟)
  - 連結至登入頁面

- [ ] **4.7 Auth 模組 — 設定頁面**
  `dashboard/src/modules/auth/pages/AccountSettings.tsx`：
  - 已連結提供者列表 (email, github, google, passkey)
  - "Link GitHub/Google" 按鈕
  - Passkey 管理 (列出憑證、新增、移除)
  - 活動中工作階段列表 (含撤銷功能)
  - 個人資料編輯 (顯示名稱、大頭照)

- [ ] **4.8 Finance 模組**
  `dashboard/src/modules/finance/`：
  - `api.ts` — `createResourceApi<Transaction>('/api/finance/transactions')` + 摘要 API
  - `hooks.ts` — `useTransactions`, `useBudgets`, `useMonthlySummary`
  - `pages/Dashboard.tsx` — 摘要卡片 (收入/支出/餘額)、類別甜甜圈圖、最近交易
  - `pages/TransactionList.tsx` — 帶有過濾功能 (類型、類別、日期範圍) 的 DataTable，建立按鈕
  - `components/TransactionForm.tsx` — 用于建立/編輯的彈窗表單
  - `components/BudgetCard.tsx` — 預算 vs 實際進度條，超出時發出警告
  - `types.ts` — Transaction, Budget, MonthlySummary 類型

- [ ] **4.9 Quest 模組**
  `dashboard/src/modules/quest/`：
  - `api.ts` — 任務 CRUD + 接受/完成/失敗動作
  - `hooks.ts` — `useQuests`, `useQuestBoard`, `useSkills`
  - `pages/QuestBoard.tsx` — 看板欄位：可用、進行中、已完成。拖放功能為選填。
  - `pages/QuestDetail.tsx` — 任務資訊、進度、XP 獎勵、動作按鈕
  - `components/QuestCard.tsx` — 卡片：標題、難度徽章、XP、狀態、截止日期
  - `components/SkillTree.tsx` — 技能與等級的樹狀/圖形視覺化
  - `types.ts` — Quest, Progress, Skill 類型

- [ ] **4.10 Muse 模組**
  `dashboard/src/modules/muse/`：
  - `api.ts` — 靈感 CRUD + 搜尋 + 連結 API
  - `hooks.ts` — `useSparks`, `useSparkSearch`, `useGraph`
  - `pages/Inbox.tsx` — 最近/未連結靈感列表，建立按鈕
  - `pages/SparkDetail.tsx` — Markdown 編輯器/檢視器，已連結靈感側邊欄
  - `components/SparkEditor.tsx` — 帶有預覽功能的 Markdown 文字區域
  - `components/LinkGraph.tsx` — 力導向圖 (canvas 或 SVG)，節點 = sparks，連線 = links
  - `types.ts` — Spark, Link, GraphData 類型

- [ ] **4.11 Admin 模組**
  `dashboard/src/modules/admin/`：
  - `api.ts` — 使用者管理 + 系統統計
  - `hooks.ts` — `useUsers`, `useSystemStats`
  - `pages/Dashboard.tsx` — 系統統計卡片 (使用者、工作階段、事件、資料庫大小)、即時動態
  - `pages/UserManagement.tsx` — 使用者 DataTable，行內角色/狀態編輯
  - `components/UserRow.tsx` — 角色下拉選單、狀態切換、最後活動時間
  - 路由守衛：僅限 admin 角色 (重新導向非管理員)
  - `types.ts` — AdminUser, SystemStats 類型

- [ ] **4.12 Shell 增強**
  `dashboard/src/shell/`：
  - `NavBar.tsx` — 使用者大頭照下拉選單 (個人資料、設定、登出)、通知鈴鐺佔位符
  - `Sidebar.tsx` — 活動路由高亮、手機上摺疊 (漢堡選單)
  - `Layout.tsx` — 手機上的底部導覽列 (<640px)，桌機上的側邊欄
  - `AppLauncher.tsx` — 動態：根據使用者角色與權限顯示/隱藏應用程式
  - 安裝 ` @simplewebauthn/browser` 以支援 passkey

- [ ] **4.13 App 路由更新**
  `dashboard/src/App.tsx`：
  - 新增路由：/account (設定), /finance/*, /quest/*, /muse/*, /admin/*
  - 認證路由：/login, /register (無守衛)
  - 針對 /admin/* 的管理員守衛
  - 404 全捕捉

- [ ] **4.14 PWA 與圖示**
  - 產生正確的 PNG 圖示 (192x192, 512x512) — 非 SVG 佔位符
  - 使用正確名稱更新 `manifest.json`
  - `sw.js` — 快取版本控制、更新通知
  - 離線備用頁面

- [ ] **4.15 驗證**
  - `pnpm build` 通過
  - 所有路由皆可導覽
  - 在 320px, 768px, 1280px 下具備響應式能力
  - 認證流程：登入 → 儀表板 → 導覽模組 → 登出
  - 無 TypeScript 錯誤，無控制台錯誤

---

## 合併順序與整合

1. [ ] 合併 `feat/infra-db` → main (資料庫結構已就緒)
2. [ ] 合併 `feat/core-engine` → main (變更基準 rebase，解決衝突)
3. [ ] 合併 `feat/domain-modules` → main (變更基準 rebase，可能需要 main.py 合併)
4. [ ] 合併 `feat/web-complete` → main (變更基準 rebase，package.json 合併)
5. [ ] 整合測試：
   - `docker compose up -d` (PG + Redis + LGTM)
   - `uv run uvicorn core.main:app --port 8800`
   - `pnpm dev` (apps/web)
   - 註冊 → 登入 → 導覽 → CRUD → 登出
6. [ ] 標記 `v2.0.0-alpha` 標籤
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
