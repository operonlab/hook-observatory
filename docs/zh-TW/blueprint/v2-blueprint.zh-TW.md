---
doc_version: 2
content_hash: 98b30e6c
source_version: 2
translated_at: 2026-02-23
---

# Workshop V2 藍圖 (修訂版)

> V1 完整功能文件化 → V2 根據架構重新構建，封裝、抽象化、繼承，最大化程式碼共用

## 設計原則

1. **抽象優先** — 共同模式抽出 `libs/`，domain modules 繼承使用
2. **Provider 模式** — Auth 使用抽象 Provider 介面，新增 provider 無須修改核心
3. **事件驅動** — 所有狀態變更皆為事件，CRUD 自動發送 (emit)
4. **慣例優於配置** — 一致的 module 結構 = 零配置新增 module

## 架構

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
              │            │  └────────┘  └─────────────┘
              │  modules:  │
              │  - auth    │
              │  - finance │
              │  - quest   │
              │  - muse    │
              │  - admin   │
              │            │
              │  engines:  │
              │  - EventBus│
              │  - HookBus │
              │  - RBAC+ABAC│
              └──┬─────┬───┘
                 │     │
           ┌─────▼─┐ ┌─▼──────┐
           │  PG   │ │ Redis  │
           │:5432  │ │ :6379  │
           └───────┘ └────────┘
```

---

## 共享函式庫 — 程式碼重用基礎

### Python (`libs/python/src/corelib/`)

```
libs/python/src/corelib/
├── config.py           # BaseSettings with common fields (host, port, debug, db_url, redis_url)
├── service.py          # BaseService[T] — generic CRUD (create, get, list, update, delete)
├── repository.py       # BaseRepository[T] — DB access (query, insert, update, delete, paginate)
├── router.py           # create_crud_router() — auto-generate CRUD routes from service+schemas
├── schemas.py          # PaginatedResponse[T], ErrorResponse, SortOrder, FilterOp
├── events.py           # CRUDEventMixin — auto-emit {domain}.{entity}.{created|updated|deleted}
├── health.py           # create_health_router() — standard /health + /health/ready
├── auth/
│   ├── provider.py     # AuthProvider ABC (authenticate, get_user_info)
│   ├── session.py      # SessionManager (DB-backed, signed cookie, TTL)
│   ├── deps.py         # get_current_user(), require_role(), require_permission()
│   └── types.py        # AuthResult, SessionPayload, UserIdentity
├── middleware/
│   ├── telemetry.py    # OTelMiddleware (auto-trace all routes)
│   ├── logging.py      # StructuredLoggingMiddleware (structlog, JSON in prod)
│   ├── errors.py       # GlobalErrorHandler ({error, code, detail, trace_id})
│   └── rate_limit.py   # RateLimitMiddleware (slowapi + Redis backend)
└── db/
    ├── pool.py         # create_pool() — psycopg async pool, lifespan integration
    └── migrations.py   # MigrationRunner — SQL files, version tracking in public.migrations
```

**關鍵抽象**：

```python
# BaseRepository — 每個 module 皆繼承此類別
class BaseRepository(Generic[T]):
    def __init__(self, pool, schema: str, table: str): ...
    async def get(self, id: UUID) -> T | None: ...
    async def list(self, filters, sort, page, size) -> PaginatedResponse[T]: ...
    async def create(self, data: dict) -> T: ...
    async def update(self, id: UUID, data: dict) -> T: ...
    async def delete(self, id: UUID) -> bool: ...

# BaseService — 編排 repo + 事件 + 權限
class BaseService(Generic[T]):
    def __init__(self, repo: BaseRepository[T], event_bus, domain: str): ...
    async def create(self, data, user) -> T:  # auto-check permission + auto-emit event
    async def get(self, id, user) -> T:       # auto-check read permission
    # ... CRUD with automatic RBAC check + event emission

# create_crud_router — 零樣板代碼的 module 路由
def create_crud_router(
    prefix: str, service: BaseService,
    create_schema, update_schema, response_schema,
    permissions: dict[str, str]  # {"create": "finance.write", "read": "finance.read"}
) -> APIRouter: ...
```

### TypeScript (`libs/typescript/src/`)

```
libs/typescript/src/
├── api/
│   ├── client.ts       # apiClient — fetch wrapper (error handling, credentials, types)
│   ├── types.ts        # PaginatedResponse<T>, ErrorResponse, ApiError
│   └── resource.ts     # createResourceApi<T>() — auto-generate CRUD api functions
├── auth/
│   ├── AuthProvider.tsx # React context (user state, login/logout/register actions)
│   ├── AuthGuard.tsx    # Route guard (redirect to login if unauthenticated)
│   ├── useAuth.ts       # Hook: useAuth() → {user, login, logout, register, isLoading}
│   └── types.ts         # User, AuthState, LoginRequest, RegisterRequest
├── components/
│   ├── DataTable.tsx    # Generic sortable, paginated, filterable table
│   ├── Modal.tsx        # Reusable modal (backdrop, close, confirm/cancel)
│   ├── Toast.tsx        # Toast notification system (success/error/warning)
│   ├── LoadingSpinner.tsx
│   ├── EmptyState.tsx   # No data placeholder with icon + message + action
│   └── ErrorBoundary.tsx
├── hooks/
│   ├── useResource.ts   # createResourceHook<T>() — CRUD hook factory (list, create, update, delete)
│   ├── usePagination.ts # Pagination state management
│   └── useWebSocket.ts  # WebSocket connection with auto-reconnect
└── types/
    └── index.ts         # Common types (AppInfo, Theme, etc.)
```

**關鍵抽象**：

```typescript
// createResourceApi — 每個 module 皆使用此功能
function createResourceApi<T>(basePath: string) {
  return {
    list: (params?) => apiClient.get<PaginatedResponse<T>>(basePath, params),
    get: (id: string) => apiClient.get<T>(`${basePath}/${id}`),
    create: (data: Partial<T>) => apiClient.post<T>(basePath, data),
    update: (id: string, data: Partial<T>) => apiClient.put<T>(`${basePath}/${id}`, data),
    delete: (id: string) => apiClient.delete(`${basePath}/${id}`),
  };
}

// createResourceHook — React hook 工廠
function createResourceHook<T>(api: ResourceApi<T>) {
  return function useResource() {
    const [items, setItems] = useState<T[]>([]);
    const [loading, setLoading] = useState(true);
    // ... list, create, update, delete with loading/error states
    return { items, loading, error, create, update, remove, refresh };
  };
}
```

---

## 認證系統 — 多 Provider 設計

### V1 與 V2 比較

| 功能 | V1 | V2 |
|---------|----|----|
| 電子郵件/密碼 | pbkdf2_sha256, passlib | **bcrypt**, passlib |
| GitHub OAuth | authlib 1.3.0 | **authlib** (保留，運作良好) |
| Google OAuth | authlib 1.3.0 | **authlib + One Tap** |
| Passkey/WebAuthn | 未實作 | **py_webauthn 2.7+** + @simplewebauthn/browser |
| 使用者儲存 | OAuth 使用者不在資料庫中 | **統一的 users 表** + provider 表 |
| 會話 (Session) | URLSafeSerializer (無過期機制) | **資料庫支援的會話** 並具備 TTL |
| 帳號連結 | 無 | **透過已驗證的電子郵件自動連結** |
| CSRF | 無 | **SameSite=lax** + 自定義標頭檢查 |
| 速率限制 | 無 | **slowapi** + Redis |
| RBAC | 無 | **角色 → 權限映射** |
| ABAC | 無 | **策略引擎** (僅限所有者、停權阻擋) |

### 資料庫 Schema

```sql
-- 核心使用者身份 (與 provider 無關)
CREATE TABLE auth.users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) UNIQUE,          -- 對於僅限 passkey 的使用者可為 NULL
    display_name    VARCHAR(255),
    avatar_url      TEXT,
    role            VARCHAR(50) NOT NULL DEFAULT 'user',   -- admin, user, guest
    status          VARCHAR(50) NOT NULL DEFAULT 'active', -- active, suspended, pending
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 電子郵件/密碼憑據
CREATE TABLE auth.local_credentials (
    user_id         UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    password_hash   VARCHAR(255) NOT NULL,         -- 透過 passlib 使用 bcrypt
    email_verified  BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- OAuth provider 帳號 (每個使用者每個 provider 一列)
CREATE TABLE auth.oauth_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider        VARCHAR(50) NOT NULL,          -- 'github' | 'google'
    provider_user_id VARCHAR(255) NOT NULL,        -- 穩定的 provider ID
    email           VARCHAR(255),                  -- 來自 provider 的電子郵件
    access_token    TEXT,                           -- 已加密
    refresh_token   TEXT,                           -- 已加密
    token_expires_at TIMESTAMPTZ,
    raw_profile     JSONB,                         -- 完整的 provider 個人檔案
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (provider, provider_user_id)
);

-- WebAuthn/Passkey 憑據
CREATE TABLE auth.webauthn_credentials (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    credential_id   BYTEA NOT NULL UNIQUE,
    public_key      BYTEA NOT NULL,                -- COSE 編碼
    sign_count      BIGINT NOT NULL DEFAULT 0,
    aaguid          UUID,
    transports      TEXT[],                        -- ["internal","usb","ble","nfc"]
    backup_eligible BOOLEAN DEFAULT FALSE,
    backup_state    BOOLEAN DEFAULT FALSE,
    device_name     VARCHAR(100),                  -- 使用者友善的標籤
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ
);

-- 伺服器端會話 (取代僅靠 cookie 的做法)
CREATE TABLE auth.sessions (
    id              VARCHAR(128) PRIMARY KEY,       -- secrets.token_urlsafe(64)
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    ip_address      INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,           -- created_at + 7 天
    last_active_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_sessions_user ON auth.sessions(user_id);
CREATE INDEX idx_sessions_expires ON auth.sessions(expires_at);
```

### Auth Provider 介面

```python
class AuthProvider(ABC):
    """所有的 auth provider 皆實作此介面。"""
    provider_name: str

    @abstractmethod
    async def authenticate(self, request: Request, **kwargs) -> AuthResult:
        """驗證憑據 → 回傳 AuthResult(user_identity, is_new_user)"""
        ...

# 實作：
# - EmailPasswordProvider    → 驗證電子郵件 + bcrypt 雜湊
# - GitHubOAuthProvider      → authlib 回呼 → token → /user + /user/emails
# - GoogleOAuthProvider      → authlib 回呼 → OIDC userinfo (+ One Tap 驗證)
# - PasskeyProvider          → py_webauthn verify_authentication_response

class AuthService:
    """編排 provider + 帳號連結 + 會話管理。"""
    providers: dict[str, AuthProvider]
    session_mgr: SessionManager

    async def authenticate(self, provider: str, **kwargs) -> Session
    async def link_account(self, user_id, provider, provider_data) -> None
    async def create_session(self, user: User, request: Request) -> Session
    async def revoke_session(self, session_id: str) -> None
    async def get_user_sessions(self, user_id: UUID) -> list[Session]
```

### 帳號連結策略

```
1. 在 oauth_accounts 檢查 (provider, provider_user_id) → 找到 → 回傳現有使用者
2. 在 users 表檢查電子郵件 → 找到且電子郵件已驗證 → 自動連結 (新增 oauth_account)
3. 未找到 → 建立新使用者 + 建立 oauth_account
```

### Auth API 端點 (V2)

| 方法 | 路徑 | 目的 |
|--------|------|---------|
| POST | /auth/register | 電子郵件/密碼註冊 |
| POST | /auth/login | 電子郵件/密碼登入 |
| POST | /auth/logout | 撤銷目前會話 |
| GET | /auth/session | 取得目前會話 + 使用者 |
| GET | /auth/sessions | 列出所有活動中的會話 |
| DELETE | /auth/sessions/{id} | 撤銷特定會話 |
| GET | /auth/oauth/github | 啟動 GitHub OAuth |
| GET | /auth/oauth/github/callback | GitHub OAuth 回呼 |
| GET | /auth/oauth/google | 啟動 Google OAuth |
| GET | /auth/oauth/google/callback | Google OAuth 回呼 |
| POST | /auth/oauth/google/one-tap | 驗證 Google One Tap 憑據 |
| GET | /auth/passkey/register/options | WebAuthn 註冊選項 |
| POST | /auth/passkey/register/verify | WebAuthn 註冊驗證 |
| GET | /auth/passkey/auth/options | WebAuthn 認證選項 |
| POST | /auth/passkey/auth/verify | WebAuthn 認證驗證 |
| GET | /auth/passkey/credentials | 列出使用者的 passkey |
| DELETE | /auth/passkey/credentials/{id} | 移除 passkey |
| GET | /auth/providers | 列出目前使用者已連結的 provider |
| POST | /auth/link/{provider} | 將新 provider 連結至現有帳號 |

---

## Domain Module 模式

每個 domain module 皆遵循相同的結構，並繼承自共享的基底類別：

### 後端 (`core/src/modules/<name>/`)

```
<name>/
├── __init__.py        # Module 註冊 (導出 router、註冊事件)
├── routes.py          # create_crud_router() + 自定義端點
├── services.py        # <Name>Service(BaseService) — 業務邏輯
├── repository.py      # <Name>Repository(BaseRepository) — 資料庫存取
├── schemas.py         # Pydantic 模型 (Create, Update, Response, Filter)
├── events.py          # 事件類型常數 + 自定義事件處理器
├── hooks.py           # 外掛擴充的掛鉤點
└── deps.py            # FastAPI 依賴項 (get_service 等)
```

### 前端 (`dashboard/src/modules/<name>/`)

```
<name>/
├── pages/             # 路由級別組件
├── components/        # Domain 專用組件
├── api.ts             # createResourceApi<T>('/api/<name>/<entity>')
├── hooks.ts           # createResourceHook(api) + 自定義 hook
├── stores.ts          # Zustand store (若除了 hook 之外還需要)
├── types.ts           # Domain 型別 (與後端 schema 匹配)
└── index.tsx          # Module 入口 (延遲載入路由)
```

### 範例：財務 (Finance) 模組

```python
# 後端：core/src/modules/finance/repository.py
class TransactionRepo(BaseRepository[Transaction]):
    def __init__(self, pool):
        super().__init__(pool, schema="finance", table="transactions")

# 後端：core/src/modules/finance/services.py
class TransactionService(BaseService[Transaction]):
    def __init__(self, repo, event_bus):
        super().__init__(repo, event_bus, domain="finance")
    # 所有 CRUD 自動產生事件：finance.transaction.created 等
    # 自定義方法：
    async def get_monthly_summary(self, user_id, year, month): ...

# 後端：core/src/modules/finance/routes.py
router = create_crud_router(
    prefix="/api/finance/transactions",
    service=transaction_service,
    create_schema=TransactionCreate,
    update_schema=TransactionUpdate,
    response_schema=TransactionResponse,
    permissions={"create": "finance.write", "read": "finance.read", ...}
)
```

```typescript
// 前端：dashboard/src/modules/finance/api.ts
export const transactionApi = createResourceApi<Transaction>('/api/finance/transactions');

// 前端：dashboard/src/modules/finance/hooks.ts
export const useTransactions = createResourceHook(transactionApi);
```

---

## 4 個平行軌道 (Worktrees)

### 更新後的依賴地圖

```
軌道 1: infra-db ─────────────────────────────────→ 優先合併
軌道 2: core-engine ──────────────────────────────→ 其次合併
軌道 3: domain-modules ── (需要 T2 基底類別) → 第三合併
軌道 4: web-complete ──── (需要 T2 API 合約) → 第四合併
         │                                              │
         ▼                                              ▼
      T1+T2 立即開始                     T3+T4 立即開始 (UI/骨架)
      T3+T4 需要 T2 合併以完成完整功能     但需要 T2 進行整合
```

### 檔案隔離

| 軌道 | 目錄 (專屬) | 潛在重疊 |
|-------|------------------------|-------------------|
| 1. infra-db | `infra/`, `docker-compose*`, `core/migrations/` | - |
| 2. core-engine | `libs/python/`, `core/src/` (引擎、認證、中間件) | `pyproject.toml`, `main.py` |
| 3. domain-modules | `core/src/modules/{finance,quest,muse,admin}/` | `main.py` (路由註冊) |
| 4. web-complete | `dashboard/`, `libs/typescript/` | `package.json` |

### 軌道 1：`feat/infra-db` — 基礎設施 + 資料庫

範圍：Docker stack + 所有資料庫 schema + 遷移系統

### 軌道 2：`feat/core-engine` — 共享函式庫 + 認證 + 引擎

範圍：Python 共享函式庫 (BaseService, BaseRepository, BaseRouter) + 完整的認證系統 (4 個 provider) + EventBus + HookBus + RBAC/ABAC + OTel + 會話管理

### 軌道 3：`feat/domain-modules` — 業務領域模組

範圍：Finance, Quest, Muse, Admin 模組 (僅後端，使用 T2 的基底類別)

### 軌道 4：`feat/web-complete` — React 前端 (完整)

範圍：TypeScript 共享函式庫 + 所有前端模組 + 認證 UI (登入、註冊、OAuth、Passkey) + shell 增強 + 共享組件

### 合併順序

1. `feat/infra-db` → main (無衝突)
2. `feat/core-engine` → main (對 main 進行 rebase，解決 pyproject.toml 衝突)
3. `feat/domain-modules` → main (rebase，解決 main.py 路由註冊衝突)
4. `feat/web-complete` → main (rebase，解決 package.json 衝突)

---

## 超出範圍 (未來計畫)

- LiveKit/WebRTC (即時服務)
- STT/TTS (多媒體服務)
- 外掛市場
- 開發者工具遷移 (獨立 sprint)
- E2E 測試
- 正式環境部署 (SigNoz, CI/CD)
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
