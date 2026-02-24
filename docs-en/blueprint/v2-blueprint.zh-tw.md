---
doc_version: 2
content_hash: 98b30e6c
source_hash: feb966f5
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# Workshop V2 Blueprint (Revised)

> V1 full functionality documented → V2 rebuilt based on architecture, encapsulating, abstracting, inheriting to maximize code sharing

## Design Principles

1.  **Abstraction First** — Extract common patterns into `libs/` to be inherited by domain modules
2.  **Provider Pattern** — Authentication (Auth) uses an abstract Provider interface, allowing new providers to be added without core modifications
3.  **Event-Driven** — All state changes are events; CRUD operations trigger (emit) them automatically
4.  **Convention Over Configuration** — A consistent module structure means no configuration is needed when adding new modules

## System Architecture

```
                    ┌─────────────────────────────────────┐
                    │          Nginx (Reverse Proxy)      │
                    │  :443 → TLS Termination             │
                    └───┬──────────┬──────────┬────────────┘
                        │          │          │
                   /auth, /api  /ws, /rtc   /tools
                        │          │          │
              ┌─────────▼──┐  ┌───▼────┐  ┌──▼──────────┐
              │ Core Service │  │Real-time Svc│  │   Tool UIs    │
              │  :8800     │  │ :8830  │  │ (respective ports)│
              │            │  └────────┘  └─────────────┘
              │  Modules:  │
              │  - auth    │
              │  - finance │
              │  - quest   │
              │  - muse    │
              │  - admin   │
              │            │
              │  Engines:  │
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

## Shared Libraries — Foundation for Code Reuse

### Python (`libs/python/src/corelib/`)

```
libs/python/src/corelib/
├── config.py           # BaseSettings with common fields (host, port, debug, db_url, redis_url)
├── service.py          # BaseService[T] — Generic CRUD (Create, Read, List, Update, Delete)
├── repository.py       # BaseRepository[T] — Database access (query, insert, update, delete, paginate)
├── router.py           # create_crud_router() — Auto-generate CRUD routes from service & schemas
├── schemas.py          # PaginatedResponse[T], ErrorResponse, SortOrder, FilterOp
├── events.py           # CRUDEventMixin — Auto-emits {domain}.{entity}.{created|updated|deleted} events
├── health.py           # create_health_router() — Standard /health and /health/ready routes
├── auth/
│   ├── provider.py     # AuthProvider abstract base class (authenticate, get_user_info)
│   ├── session.py      # SessionManager (DB-backed, signed cookies, TTL)
│   ├── deps.py         # get_current_user(), require_role(), require_permission()
│   └── types.py        # AuthResult, SessionPayload, UserIdentity
├── middleware/
│   ├── telemetry.py    # OTelMiddleware (Auto-traces all routes)
│   ├── logging.py      # StructuredLoggingMiddleware (Structured logging, uses JSON in prod)
│   ├── errors.py       # Global error handler ({error, code, detail, trace_id})
│   └── rate_limit.py   # Rate limiting middleware (using slowapi + Redis backend)
└── db/
    ├── pool.py         # create_pool() — psycopg async connection pool, integrated with app lifecycle
    └── migrations.py   # MigrationRunner — Runs SQL files, tracks version in public.migrations
```

**Key Abstractions**:

```python
# BaseRepository — Every module inherits this
class BaseRepository(Generic[T]):
    def __init__(self, pool, schema: str, table: str): ...
    async def get(self, id: UUID) -> T | None: ...
    async def list(self, filters, sort, page, size) -> PaginatedResponse[T]: ...
    async def create(self, data: dict) -> T: ...
    async def update(self, id: UUID, data: dict) -> T: ...
    async def delete(self, id: UUID) -> bool: ...

# BaseService — Orchestrates repo, events, and permissions
class BaseService(Generic[T]):
    def __init__(self, repo: BaseRepository[T], event_bus, domain: str): ...
    async def create(self, data, user) -> T:  # Auto-checks permissions + auto-emits event
    async def get(self, id, user) -> T:       # Auto-checks read permission
    # ... rest of CRUD has auto RBAC checks and event emission

# create_crud_router — Zero-boilerplate module routes
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
│   ├── client.ts       # apiClient — wrapper for fetch (error handling, credentials, types)
│   ├── types.ts        # PaginatedResponse<T>, ErrorResponse, ApiError
│   └── resource.ts     # createResourceApi<T>() — Auto-generates CRUD API functions
├── auth/
│   ├── AuthProvider.tsx # React context (user state, login/logout/register actions)
│   ├── AuthGuard.tsx    # Route guard (redirects to login if not authenticated)
│   ├── useAuth.ts       # Hook: useAuth() → {user, login, logout, register, isLoading}
│   └── types.ts         # User, AuthState, LoginRequest, RegisterRequest
├── components/
│   ├── DataTable.tsx    # Generic sortable, paginated, filterable table
│   ├── Modal.tsx        # Reusable modal (backdrop, close, confirm/cancel)
│   ├── Toast.tsx        # Toast notification system (success/error/warn)
│   ├── LoadingSpinner.tsx
│   ├── EmptyState.tsx   # Placeholder for when there's no data (icon + message + action)
│   └── ErrorBoundary.tsx
├── hooks/
│   ├── useResource.ts   # createResourceHook<T>() — CRUD hook factory (list, create, update, delete)
│   ├── usePagination.ts # Pagination state management
│   └── useWebSocket.ts  # WebSocket connection with auto-reconnect
└── types/
    └── index.ts         # Common types (AppInfo, Theme, etc.)
```

**Key Abstractions**:

```typescript
// createResourceApi — Every module uses this
function createResourceApi<T>(basePath: string) {
  return {
    list: (params?) => apiClient.get<PaginatedResponse<T>>(basePath, params),
    get: (id: string) => apiClient.get<T>(`${basePath}/${id}`),
    create: (data: Partial<T>) => apiClient.post<T>(basePath, data),
    update: (id: string, data: Partial<T>) => apiClient.put<T>(`${basePath}/${id}`, data),
    delete: (id: string) => apiClient.delete(`${basePath}/${id}`),
  };
}

// createResourceHook — React hook factory
function createResourceHook<T>(api: ResourceApi<T>) {
  return function useResource() {
    const [items, setItems] = useState<T[]>([]);
    const [loading, setLoading] = useState(true);
    // ... list, create, update, delete functions with loading/error state
    return { items, loading, error, create, update, remove, refresh };
  };
}
```

---

## Auth System — Multi-Provider Design

### V1 → V2 Comparison

| Feature | V1 | V2 |
|---------|----|----|
| Email/Pass | pbkdf2_sha256, passlib | **bcrypt**, passlib |
| GitHub OAuth | authlib 1.3.0 | **authlib** (kept, works well) |
| Google OAuth | authlib 1.3.0 | **authlib + One Tap** |
| Passkey/WebAuthn | Not implemented | **py_webauthn 2.7+** + @simplewebauthn/browser |
| User Storage | OAuth users not in DB | **Unified user table** + provider tables |
| Session | URLSafeSerializer (no expiry) | **DB-backed sessions** with TTL |
| Account Linking | No | **Auto-linking via verified email** |
| CSRF | No | **SameSite=lax** + custom header check |
| Rate Limiting | No | **slowapi** + Redis |
| RBAC | No | **Role → Permission mapping** |
| ABAC | No | **Policy engine** (owner-only, block if suspended) |

### Database Schema

```sql
-- Core user identity (provider-agnostic)
CREATE TABLE auth.users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) UNIQUE,          -- can be NULL for passkey-only users
    display_name    VARCHAR(255),
    avatar_url      TEXT,
    role            VARCHAR(50) NOT NULL DEFAULT 'user',   -- admin, user, guest
    status          VARCHAR(50) NOT NULL DEFAULT 'active', -- active, suspended, pending
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Email/password credentials
CREATE TABLE auth.local_credentials (
    user_id         UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    password_hash   VARCHAR(255) NOT NULL,         -- bcrypt via passlib
    email_verified  BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- OAuth provider accounts (one row per user, per provider)
CREATE TABLE auth.oauth_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider        VARCHAR(50) NOT NULL,          -- 'github' | 'google'
    provider_user_id VARCHAR(255) NOT NULL,        -- stable provider user ID
    email           VARCHAR(255),                  -- email from provider
    access_token    TEXT,                           -- encrypted
    refresh_token   TEXT,                           -- encrypted
    token_expires_at TIMESTAMPTZ,
    raw_profile     JSONB,                         -- full provider profile
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (provider, provider_user_id)
);

-- WebAuthn/Passkey credentials
CREATE TABLE auth.webauthn_credentials (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    credential_id   BYTEA NOT NULL UNIQUE,
    public_key      BYTEA NOT NULL,                -- COSE encoded
    sign_count      BIGINT NOT NULL DEFAULT 0,
    aaguid          UUID,
    transports      TEXT[],                        -- ["internal","usb","ble","nfc"]
    backup_eligible BOOLEAN DEFAULT FALSE,
    backup_state    BOOLEAN DEFAULT FALSE,
    device_name     VARCHAR(100),                  -- user-friendly label
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ
);

-- Server-side sessions (replaces pure cookie approach)
CREATE TABLE auth.sessions (
    id              VARCHAR(128) PRIMARY KEY,       -- secrets.token_urlsafe(64)
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    ip_address      INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,           -- created_at + 7 days
    last_active_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_sessions_user ON auth.sessions(user_id);
CREATE INDEX idx_sessions_expires ON auth.sessions(expires_at);
```

### Auth Provider Interface

```python
class AuthProvider(ABC):
    """All auth providers implement this interface."""
    provider_name: str

    @abstractmethod
    async def authenticate(self, request: Request, **kwargs) -> AuthResult:
        """Authenticates credentials → returns AuthResult(user_identity, is_new_user)"""
        ...

# Implementations:
# - EmailPasswordProvider    → validates email + bcrypt hash
# - GitHubOAuthProvider      → authlib callback → token → /user + /user/emails
# - GoogleOAuthProvider      → authlib callback → OIDC userinfo (+ One Tap validation)
# - PasskeyProvider          → py_webauthn verify_authentication_response

class AuthService:
    """Orchestrates providers, account linking, and session management."""
    providers: dict[str, AuthProvider]
    session_mgr: SessionManager

    async def authenticate(self, provider: str, **kwargs) -> Session
    async def link_account(self, user_id, provider, provider_data) -> None
    async def create_session(self, user: User, request: Request) -> Session
    async def revoke_session(self, session_id: str) -> None
    async def get_user_sessions(self, user_id: UUID) -> list[Session]
```

### Account Linking Strategy

```
1. Check for (provider, provider_user_id) in oauth_accounts → if found → return existing user
2. Check for email in users table → if found and email is verified → auto-link (add oauth_account)
3. If not found → create new user + create oauth_account
```

### Auth API Endpoints (V2)

| Method | Path | Purpose |
|--------|------|---------|
| POST | /auth/register | Email/Password Registration |
| POST | /auth/login | Email/Password Login |
| POST | /auth/logout | Revoke current session |
| GET | /auth/session | Get current session + user |
| GET | /auth/sessions | List all active sessions |
| DELETE | /auth/sessions/{id} | Revoke specific session |
| GET | /auth/oauth/github | Initiate GitHub OAuth |
| GET | /auth/oauth/github/callback | GitHub OAuth callback |
| GET | /auth/oauth/google | Initiate Google OAuth |
| GET | /auth/oauth/google/callback | Google OAuth callback |
| POST | /auth/oauth/google/one-tap | Validate Google One Tap credential |
| GET | /auth/passkey/register/options | WebAuthn registration options |
| POST | /auth/passkey/register/verify | WebAuthn registration verification |
| GET | /auth/passkey/auth/options | WebAuthn authentication options |
| POST | /auth/passkey/auth/verify | WebAuthn authentication verification |
| GET | /auth/passkey/credentials | List user's passkeys |
| DELETE | /auth/passkey/credentials/{id} | Remove a passkey |
| GET | /auth/providers | List current user's linked providers |
| POST | /auth/link/{provider} | Link a new provider to existing account |

---

## Domain Module Pattern

Each domain module follows the same structure, inheriting from shared base classes:

### Backend (`core/src/modules/<name>/`)

```
<name>/
├── __init__.py        # Module registration (export router, register events)
├── routes.py          # create_crud_router() + custom endpoints
├── services.py        # <Name>Service(BaseService) — Business logic
├── repository.py      # <Name>Repository(BaseRepository) — DB access
├── schemas.py         # Pydantic models (Create, Update, Response, Filter)
├── events.py          # Event type constants + custom handlers
├── hooks.py           # Hook points for plugin extension
└── deps.py            # FastAPI dependencies (get_service, etc)
```

### Frontend (`workbench/src/modules/<name>/`)

```
<name>/
├── pages/             # Route-level components
├── components/        # Domain-specific components
├── api.ts             # createResourceApi<T>('/api/<name>/<entity>')
├── hooks.ts           # createResourceHook(api) + custom hooks
├── stores.ts          # Zustand stores (if hooks aren't enough)
├── types.ts           # Domain types (mirroring backend schemas)
└── index.tsx          # Module entrypoint (lazy-loaded routes)
```

### Example: Finance Module

```python
# Backend: core/src/modules/finance/repository.py
class TransactionRepo(BaseRepository[Transaction]):
    def __init__(self, pool):
        super().__init__(pool, schema="finance", table="transactions")

# Backend: core/src/modules/finance/services.py
class TransactionService(BaseService[Transaction]):
    def __init__(self, repo, event_bus):
        super().__init__(repo, event_bus, domain="finance")
    # All CRUD operations auto-generate events: finance.transaction.created, etc.
    # Custom methods:
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

## 4 Parallel Workstreams (Worktrees)

### Updated Dependency Graph

```
Track 1: infra-db ─────────────────────────────────→ Merged First
Track 2: core-engine ──────────────────────────────→ Merged Second
Track 3: domain-modules ── (needs T2 base classes) → Merged Third
Track 4: web-complete ──── (needs T2 API contract) → Merged Fourth
         │                                              │
         ▼                                              ▼
      T1+T2 can start immediately        T3+T4 can start immediately (UI/skeleton)
      T3+T4 needs T2 merge for full functionality, but T2 for integration
```

### File Isolation

| Track | Directories (Exclusive) | Potential Overlap |
|-------|------------------------|-------------------|
| 1. infra-db | `infra/`, `docker-compose*`, `core/migrations/` | - |
| 2. core-engine | `libs/python/`, `core/src/` (engine, auth, middleware) | `pyproject.toml`, `main.py` |
| 3. domain-modules | `core/src/modules/{finance,quest,muse,admin}/` | `main.py` (route registration) |
| 4. web-complete | `workbench/`, `libs/typescript/` | `package.json` |

### Track 1: `feat/infra-db` — Infrastructure + Database

Scope: Docker stack + all DB schema + migration system

### Track 2: `feat/core-engine` — Shared Libs + Auth + Engine

Scope: Python shared libs (BaseService, BaseRepository, BaseRouter) + full Auth system (4 providers) + EventBus + HookBus + RBAC/ABAC + OTel + session management

### Track 3: `feat/domain-modules` — Business Domain Modules

Scope: Finance, Quest, Muse, Admin modules (backend only, using T2's base classes)

### Track 4: `feat/web-complete` — React Frontend (Full)

Scope: TypeScript shared libs + all frontend modules + Auth UI (Login, Register, OAuth, Passkey) + Shell Enhancements + Shared Components

### Merge Order

1. `feat/infra-db` → main (no conflicts)
2. `feat/core-engine` → main (rebase on main, resolve pyproject.toml conflict)
3. `feat/domain-modules` → main (rebase, resolve route registration in main.py)
4. `feat/web-complete` → main (rebase, resolve package.json conflict)

---

## Out of Scope (Future Plans)

- LiveKit/WebRTC (Real-time service)
- STT/TTS (Media service)
- Plugin Marketplace
- Dev-tools migration (separate sprint)
- E2E tests
- Production deployment (SigNoz, CI/CD)
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2397ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2383ms
