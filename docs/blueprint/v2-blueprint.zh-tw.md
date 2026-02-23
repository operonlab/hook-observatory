
---
doc_version: 2
content_hash: 98b30e6c
---

# Workshop V2 藍圖 (修訂版)

> V1 完整功能文件化 → V2 根據架構重新構建，封裝、抽象化、繼承，最大化程式碼共用

## 設計原則

1.  **抽象優先** — 將共通模式提取至 `libs/`，由領域模組繼承使用
2.  **提供者模式** — 認證(Auth)採用抽象的 Provider 介面，新增提供者時無需修改核心
3.  **事件驅動** — 所有狀態變更皆為事件，CRUD 操作自動觸發 (emit)
4.  **慣例優於設定** — 一致的模組結構意味著新增模組時無需設定

## 系統架構

```
                    ┌─────────────────────────────────────┐
                    │            Nginx (反向代理)         │
                    │  :443 → TLS 終止                     │
                    └───┬──────────┬──────────┬────────────┘
                        │          │          │
                   /auth, /api  /ws, /rtc   /tools
                        │          │          │
              ┌─────────▼──┐  ┌───▼────┐  ┌──▼──────────┐
              │  核心服務  │  │即時服務│  │ 工具使用者介面 │
              │  :8800     │  │ :8830  │  │  (各自的連接埠) │
              │            │  └────────┘  └─────────────┘
              │  模組:     │
              │  - auth    │
              │  - finance │
              │  - quest   │
              │  - muse    │
              │  - admin   │
              │            │
              │  引擎:     │
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

## 共享函式庫 — 程式碼複用基礎

### Python (`libs/python/src/corelib/`)

```
libs/python/src/corelib/
├── config.py           # 包含通用欄位 (host, port, debug, db_url, redis_url) 的 BaseSettings
├── service.py          # BaseService[T] — 通用的 CRUD (建立、讀取、列表、更新、刪除)
├── repository.py       # BaseRepository[T] — 資料庫存取 (查詢、插入、更新、刪除、分頁)
├── router.py           # create_crud_router() — 從 service 與 schemas 自動生成 CRUD 路由
├── schemas.py          # PaginatedResponse[T], ErrorResponse, SortOrder, FilterOp
├── events.py           # CRUDEventMixin — 自動觸發 {domain}.{entity}.{created|updated|deleted} 事件
├── health.py           # create_health_router() — 標準的 /health 與 /health/ready 路由
├── auth/
│   ├── provider.py     # AuthProvider 抽象基礎類別 (authenticate, get_user_info)
│   ├── session.py      # SessionManager (資料庫支援、簽名 cookie、存活時間)
│   ├── deps.py         # get_current_user(), require_role(), require_permission()
│   └── types.py        # AuthResult, SessionPayload, UserIdentity
├── middleware/
│   ├── telemetry.py    # OTelMiddleware (自動追蹤所有路由)
│   ├── logging.py      # StructuredLoggingMiddleware (結構化日誌, 生產環境使用 JSON)
│   ├── errors.py       # 全域錯誤處理器 ({error, code, detail, trace_id})
│   └── rate_limit.py   # 速率限制中介軟體 (使用 slowapi + Redis 後端)
└── db/
    ├── pool.py         # create_pool() — psycopg 非同步連線池，與應用生命週期整合
    └── migrations.py   # MigrationRunner — 執行 SQL 檔案，並在 public.migrations 中追蹤版本
```

**關鍵抽象**:

```python
# BaseRepository — 每個模組都繼承此類別
class BaseRepository(Generic[T]):
    def __init__(self, pool, schema: str, table: str): ...
    async def get(self, id: UUID) -> T | None: ...
    async def list(self, filters, sort, page, size) -> PaginatedResponse[T]: ...
    async def create(self, data: dict) -> T: ...
    async def update(self, id: UUID, data: dict) -> T: ...
    async def delete(self, id: UUID) -> bool: ...

# BaseService — 協調 repository、事件與權限
class BaseService(Generic[T]):
    def __init__(self, repo: BaseRepository[T], event_bus, domain: str): ...
    async def create(self, data, user) -> T:  # 自動檢查權限 + 自動觸發事件
    async def get(self, id, user) -> T:       # 自動檢查讀取權限
    # ... 其餘 CRUD 操作皆具備自動 RBAC 檢查與事件觸發

# create_crud_router — 零樣板程式碼的模組路由
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
│   ├── client.ts       # apiClient — fetch 的封裝 (錯誤處理、憑證、類型)
│   ├── types.ts        # PaginatedResponse<T>, ErrorResponse, ApiError
│   └── resource.ts     # createResourceApi<T>() — 自動生成 CRUD API 函數
├── auth/
│   ├── AuthProvider.tsx # React context (使用者狀態、登入/登出/註冊動作)
│   ├── AuthGuard.tsx    # 路由守衛 (未驗證則重導向至登入頁)
│   ├── useAuth.ts       # Hook: useAuth() → {user, login, logout, register, isLoading}
│   └── types.ts         # User, AuthState, LoginRequest, RegisterRequest
├── components/
│   ├── DataTable.tsx    # 通用的可排序、可分頁、可篩選的表格
│   ├── Modal.tsx        # 可重複使用的模態視窗 (背景、關閉、確認/取消)
│   ├── Toast.tsx        # Toast 通知系統 (成功/錯誤/警告)
│   ├── LoadingSpinner.tsx
│   ├── EmptyState.tsx   # 無資料時的佔位符 (圖示 + 訊息 + 動作)
│   └── ErrorBoundary.tsx
├── hooks/
│   ├── useResource.ts   # createResourceHook<T>() — CRUD hook 工廠 (列表、建立、更新、刪除)
│   ├── usePagination.ts # 分頁狀態管理
│   └── useWebSocket.ts  # WebSocket 連線，具備自動重連功能
└── types/
    └── index.ts         # 通用類型 (AppInfo, Theme 等)
```

**關鍵抽象**:

```typescript
// createResourceApi — 每個模組都使用此函數
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
    // ... 包含載入/錯誤狀態的列表、建立、更新、刪除功能
    return { items, loading, error, create, update, remove, refresh };
  };
}
```

---

## 認證系統 — 多提供者設計

### V1 → V2 比較

| 功能 | V1 | V2 |
|---------|----|----|
| 電子郵件/密碼 | pbkdf2_sha256, passlib | **bcrypt**, passlib |
| GitHub OAuth | authlib 1.3.0 | **authlib** (保留，運作良好) |
| Google OAuth | authlib 1.3.0 | **authlib + One Tap** |
| Passkey/WebAuthn | 未實作 | **py_webauthn 2.7+** + @simplewebauthn/browser |
| 使用者儲存 | OAuth 使用者不在資料庫中 | **統一的使用者資料表** + 提供者資料表 |
| 會話 | URLSafeSerializer (無過期時間) | **資料庫支援的會話** 並具備 TTL |
| 帳號連結 | 無 | **透過已驗證的電子郵件自動連結** |
| CSRF | 無 | **SameSite=lax** + 自訂標頭檢查 |
| 速率限制 | 無 | **slowapi** + Redis |
| RBAC | 無 | **角色 → 權限對應** |
| ABAC | 無 | **策略引擎** (僅擁有者、已停權則封鎖) |

### 資料庫結構

```sql
-- 核心使用者身份 (與提供者無關)
CREATE TABLE auth.users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) UNIQUE,          -- 對於僅使用 passkey 的使用者可為 NULL
    display_name    VARCHAR(255),
    avatar_url      TEXT,
    role            VARCHAR(50) NOT NULL DEFAULT 'user',   -- admin, user, guest
    status          VARCHAR(50) NOT NULL DEFAULT 'active', -- active (啟用), suspended (停權), pending (待定)
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 電子郵件/密碼憑證
CREATE TABLE auth.local_credentials (
    user_id         UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    password_hash   VARCHAR(255) NOT NULL,         -- 透過 passlib 使用 bcrypt
    email_verified  BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- OAuth 提供者帳號 (每個使用者、每個提供者一列)
CREATE TABLE auth.oauth_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider        VARCHAR(50) NOT NULL,          -- 'github' | 'google'
    provider_user_id VARCHAR(255) NOT NULL,        -- 穩定的提供者使用者 ID
    email           VARCHAR(255),                  -- 來自提供者的電子郵件
    access_token    TEXT,                           -- 已加密
    refresh_token   TEXT,                           -- 已加密
    token_expires_at TIMESTAMPTZ,
    raw_profile     JSONB,                         -- 完整的提供者個人資料
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (provider, provider_user_id)
);

-- WebAuthn/Passkey 憑證
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

-- 伺服器端會話 (取代純 cookie 的作法)
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

### 認證提供者介面

```python
class AuthProvider(ABC):
    """所有認證提供者都實作此介面。"""
    provider_name: str

    @abstractmethod
    async def authenticate(self, request: Request, **kwargs) -> AuthResult:
        """驗證憑證 → 回傳 AuthResult(user_identity, is_new_user)"""
        ...

# 實作：
# - EmailPasswordProvider    → 驗證 email + bcrypt 雜湊
# - GitHubOAuthProvider      → authlib 回呼 → token → /user + /user/emails
# - GoogleOAuthProvider      → authlib 回呼 → OIDC userinfo (+ One Tap 驗證)
# - PasskeyProvider          → py_webauthn verify_authentication_response

class AuthService:
    """協調各提供者、帳號連結與會話管理。"""
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
1. 在 oauth_accounts 中檢查 (provider, provider_user_id) → 若找到 → 回傳現有使用者
2. 在 users 資料表中檢查 email → 若找到且 email 已驗證 → 自動連結 (新增 oauth_account)
3. 若未找到 → 建立新使用者 + 建立 oauth_account
```

### 認證 API 端點 (V2)

| 方法 | 路徑 | 目的 |
|--------|------|---------|
| POST | /auth/register | 電子郵件/密碼註冊 |
| POST | /auth/login | 電子郵件/密碼登入 |
| POST | /auth/logout | 撤銷目前會話 |
| GET | /auth/session | 取得目前會話 + 使用者 |
| GET | /auth/sessions | 列出所有活動中會話 |
| DELETE | /auth/sessions/{id} | 撤銷指定會話 |
| GET | /auth/oauth/github | 啟動 GitHub OAuth |
| GET | /auth/oauth/github/callback | GitHub OAuth 回呼 |
| GET | /auth/oauth/google | 啟動 Google OAuth |
| GET | /auth/oauth/google/callback | Google OAuth 回呼 |
| POST | /auth/oauth/google/one-tap | 驗證 Google One Tap 憑證 |
| GET | /auth/passkey/register/options | WebAuthn 註冊選項 |
| POST | /auth/passkey/register/verify | WebAuthn 註冊驗證 |
| GET | /auth/passkey/auth/options | WebAuthn 認證選項 |
| POST | /auth/passkey/auth/verify | WebAuthn 認證驗證 |
| GET | /auth/passkey/credentials | 列出使用者的 passkey |
| DELETE | /auth/passkey/credentials/{id} | 移除 passkey |
| GET | /auth/providers | 列出目前使用者已連結的提供者 |
| POST | /auth/link/{provider} | 將新提供者連結至現有帳號 |

---

## 領域模組模式

每個領域模組都遵循相同的結構，並繼承自共享的基礎類別：

### 後端 (`core/src/modules/<name>/`)

```
<name>/
├── __init__.py        # 模組註冊 (匯出 router, 註冊事件)
├── routes.py          # create_crud_router() + 自訂端點
├── services.py        # <Name>Service(BaseService) — 商業邏輯
├── repository.py      # <Name>Repository(BaseRepository) — 資料庫存取
├── schemas.py         # Pydantic 模型 (建立、更新、回應、篩選)
├── events.py          # 事件類型常數 + 自訂事件處理器
├── hooks.py           # 用於外掛擴充的掛鉤點
└── deps.py            # FastAPI 依賴項 (get_service 等)
```

### 前端 (`workbench/src/modules/<name>/`)

```
<name>/
├── pages/             # 路由層級的元件
├── components/        # 領域特定的元件
├── api.ts             # createResourceApi<T>('/api/<name>/<entity>')
├── hooks.ts           # createResourceHook(api) + 自訂 hooks
├── stores.ts          # Zustand 狀態儲存 (若 hooks 不足時使用)
├── types.ts           # 領域類型 (與後端 schemas 對應)
└── index.tsx          # 模組進入點 (延遲載入的路由)
```

### 範例：財物模組

```python
# Backend: core/src/modules/finance/repository.py
class TransactionRepo(BaseRepository[Transaction]):
    def __init__(self, pool):
        super().__init__(pool, schema="finance", table="transactions")

# Backend: core/src/modules/finance/services.py
class TransactionService(BaseService[Transaction]):
    def __init__(self, repo, event_bus):
        super().__init__(repo, event_bus, domain="finance")
    # 所有 CRUD 操作都會自動生成事件：finance.transaction.created 等
    # 自訂方法：
    async def get_monthly_summary(self, user_id, year, month): ...

# Backend: core/src/modules/finance/routes.py
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
// Frontend: workbench/src/modules/finance/api.ts
export const transactionApi = createResourceApi<Transaction>('/api/finance/transactions');

// Frontend: workbench/src/modules/finance/hooks.ts
export const useTransactions = createResourceHook(transactionApi);
```

---

## 4 個平行軌道 (Worktrees)

### 更新後的依賴關係圖

```
軌道 1: infra-db ─────────────────────────────────→ 首先合併
軌道 2: core-engine ──────────────────────────────→ 第二順位合併
軌道 3: domain-modules ── (需要 T2 基礎類別) → 第三順位合併
軌道 4: web-complete ──── (需要 T2 API 合約) → 第四順位合併
         │                                              │
         ▼                                              ▼
      T1+T2 立即開始                     T3+T4 立即開始 (UI/骨架)
      T3+T4 需要 T2 合併以完成全部功能，但需要 T2 進行整合
```

### 檔案隔離

| 軌道 | 目錄 (獨佔) | 潛在重疊 |
|-------|------------------------|-------------------|
| 1. infra-db | `infra/`, `docker-compose*`, `core/migrations/` | - |
| 2. core-engine | `libs/python/`, `core/src/` (引擎、認證、中介軟體) | `pyproject.toml`, `main.py` |
| 3. domain-modules | `core/src/modules/{finance,quest,muse,admin}/` | `main.py` (路由註冊) |
| 4. web-complete | `workbench/`, `libs/typescript/` | `package.json` |

### 軌道 1: `feat/infra-db` — 基礎設施 + 資料庫

範疇: Docker 堆疊 + 所有資料庫結構 + 遷移系統

### 軌道 2: `feat/core-engine` — 共享函式庫 + 認證 + 引擎

範疇: Python 共享函式庫 (BaseService, BaseRepository, BaseRouter) + 完整的認證系統 (4 個提供者) + EventBus + HookBus + RBAC/ABAC + OTel + 會話管理

### 軌道 3: `feat/domain-modules` — 商業領域模組

範疇: 財物、任務、靈感、管理模組 (僅後端，使用 T2 的基礎類別)

### 軌道 4: `feat/web-complete` — React 前端 (完整)

範疇: TypeScript 共享函式庫 + 所有前端模組 + 認證 UI (登入、註冊、OAuth、Passkey) + 外殼增強 + 共享元件

### 合併順序

1. `feat/infra-db` → main (無衝突)
2. `feat/core-engine` → main (在 main 上 rebase, 解決 pyproject.toml 衝突)
3. `feat/domain-modules` → main (rebase, 解決 main.py 中的路由註冊衝突)
4. `feat/web-complete` → main (rebase, 解決 package.json 衝突)

---

## 範圍之外 (未來規劃)

- LiveKit/WebRTC (即時服務)
- STT/TTS (媒體服務)
- 外掛市集
- 開發者工具遷移 (獨立的衝刺)
- 端對端測試
- 生產環境部署 (SigNoz, CI/CD)
