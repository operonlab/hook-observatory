---
doc_version: 2
content_hash: 98b30e6c
source_hash: 8727c38e
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# Workshop V2 Blueprint (Revised)

> V1: Documenting full functionality → V2: Rebuilding based on architecture, using encapsulation, abstraction, and inheritance to maximize code reuse.

## Design Principles

1.  **Abstract first** — Extract common patterns into `libs/`, allowing domain modules to inherit and use them.
2.  **Provider pattern** — Auth uses an abstract Provider interface, so adding new providers doesn't require core changes.
3.  **Event-driven** — All state changes are events; CRUD operations automatically emit them.
4.  **Convention over config** — A consistent module structure enables adding new modules with zero configuration.

## Architecture

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

## Shared Libraries — Code Reuse Foundation

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

**Key abstractions**:

```python
# BaseRepository — every module inherits this
class BaseRepository(Generic[T]):
    def __init__(self, pool, schema: str, table: str): ...
    async def get(self, id: UUID) -> T | None: ...
    async def list(self, filters, sort, page, size) -> PaginatedResponse[T]: ...
    async def create(self, data: dict) -> T: ...
    async def update(self, id: UUID, data: dict) -> T: ...
    async def delete(self, id: UUID) -> bool: ...

# BaseService — orchestrates repo + events + permissions
class BaseService(Generic[T]):
    def __init__(self, repo: BaseRepository[T], event_bus, domain: str): ...
    async def create(self, data, user) -> T:  # auto-check permission + auto-emit event
    async def get(self, id, user) -> T:       # auto-check read permission
    # ... CRUD with automatic RBAC check + event emission

# create_crud_router — zero-boilerplate module routes
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

**Key abstraction**:

```typescript
// createResourceApi — every module uses this
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
    // ... list, create, update, delete with loading/error states
    return { items, loading, error, create, update, remove, refresh };
  };
}
```

---

## Auth System — Multi-Provider Design

### V1 → V2 Comparison

| Feature | V1 | V2 |
|---------|----|----|
| Email/Password | pbkdf2_sha256, passlib | **bcrypt**, passlib |
| GitHub OAuth | authlib 1.3.0 | **authlib** (keep, works well) |
| Google OAuth | authlib 1.3.0 | **authlib + One Tap** |
| Passkey/WebAuthn | Not implemented | **py_webauthn 2.7+** + @simplewebauthn/browser |
| User storage | OAuth users NOT in DB | **Unified users table** + provider tables |
| Session | URLSafeSerializer (no expiry) | **DB-backed sessions** with TTL |
| Account linking | None | **Auto-link by verified email** |
| CSRF | None | **SameSite=lax** + custom header check |
| Rate limiting | None | **slowapi** + Redis |
| RBAC | None | **Role → permissions map** |
| ABAC | None | **Policy engine** (owner-only, suspended block) |

### Database Schema

```sql
-- Core user identity (provider-agnostic)
CREATE TABLE auth.users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) UNIQUE,          -- NULL for passkey-only users
    display_name    VARCHAR(255),
    avatar_url      TEXT,
    role            VARCHAR(50) NOT NULL DEFAULT 'user',   -- admin, user, guest
    status          VARCHAR(50) NOT NULL DEFAULT 'active', -- active, suspended, pending
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Email/Password credentials
CREATE TABLE auth.local_credentials (
    user_id         UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    password_hash   VARCHAR(255) NOT NULL,         -- bcrypt via passlib
    email_verified  BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- OAuth provider accounts (one row per provider per user)
CREATE TABLE auth.oauth_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider        VARCHAR(50) NOT NULL,          -- 'github' | 'google'
    provider_user_id VARCHAR(255) NOT NULL,        -- stable provider ID
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
    public_key      BYTEA NOT NULL,                -- COSE-encoded
    sign_count      BIGINT NOT NULL DEFAULT 0,
    aaguid          UUID,
    transports      TEXT[],                        -- ["internal","usb","ble","nfc"]
    backup_eligible BOOLEAN DEFAULT FALSE,
    backup_state    BOOLEAN DEFAULT FALSE,
    device_name     VARCHAR(100),                  -- user-friendly label
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ
);

-- Server-side sessions (replace cookie-only approach)
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
        """Verify credentials → return AuthResult(user_identity, is_new_user)"""
        ...

# Implementations:
# - EmailPasswordProvider    → verify email + bcrypt hash
# - GitHubOAuthProvider      → authlib callback → token → /user + /user/emails
# - GoogleOAuthProvider      → authlib callback → OIDC userinfo (+ One Tap verify)
# - PasskeyProvider          → py_webauthn verify_authentication_response

class AuthService:
    """Orchestrates providers + account linking + session management."""
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
1. Check (provider, provider_user_id) in oauth_accounts → found → return existing user
2. Check email in users table → found + email verified → auto-link (add oauth_account)
3. Not found → create new user + create oauth_account
```

### Auth API Endpoints (V2)

| Method | Path | Purpose |
|--------|------|---------|
| POST | /auth/register | Email/password registration |
| POST | /auth/login | Email/password login |
| POST | /auth/logout | Revoke current session |
| GET | /auth/session | Get current session + user |
| GET | /auth/sessions | List all active sessions |
| DELETE | /auth/sessions/{id} | Revoke specific session |
| GET | /auth/oauth/github | Initiate GitHub OAuth |
| GET | /auth/oauth/github/callback | GitHub OAuth callback |
| GET | /auth/oauth/google | Initiate Google OAuth |
| GET | /auth/oauth/google/callback | Google OAuth callback |
| POST | /auth/oauth/google/one-tap | Verify Google One Tap credential |
| GET | /auth/passkey/register/options | WebAuthn registration options |
| POST | /auth/passkey/register/verify | WebAuthn registration verify |
| GET | /auth/passkey/auth/options | WebAuthn auth options |
| POST | /auth/passkey/auth/verify | WebAuthn auth verify |
| GET | /auth/passkey/credentials | List user's passkeys |
| DELETE | /auth/passkey/credentials/{id} | Remove a passkey |
| GET | /auth/providers | List linked providers for current user |
| POST | /auth/link/{provider} | Link new provider to existing account |

---

## Domain Module Pattern

Every domain module follows the same structure, inheriting from shared base classes:

### Backend (`core/src/modules/<name>/`)

```
<name>/
├── __init__.py        # Module registration (export router, register events)
├── routes.py          # create_crud_router() + custom endpoints
├── services.py        # <Name>Service(BaseService) — business logic
├── repository.py      # <Name>Repository(BaseRepository) — DB access
├── schemas.py         # Pydantic models (Create, Update, Response, Filter)
├── events.py          # Event type constants + custom event handlers
├── hooks.py           # Hook points for plugin extension
└── deps.py            # FastAPI dependencies (get_service, etc.)
```

### Frontend (`workbench/src/modules/<name>/`)

```
<name>/
├── pages/             # Route-level components
├── components/        # Domain-specific components
├── api.ts             # createResourceApi<T>('/api/<name>/<entity>')
├── hooks.ts           # createResourceHook(api) + custom hooks
├── stores.ts          # Zustand store (if needed beyond hooks)
├── types.ts           # Domain types (matching backend schemas)
└── index.tsx          # Module entry (lazy-loaded routes)
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
    # All CRUD auto-generates events: finance.transaction.created, etc.
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

## 4 Parallel Tracks (Worktrees)

### Updated Dependency Map

```
Track 1: infra-db ─────────────────────────────────→ merge FIRST
Track 2: core-engine ──────────────────────────────→ merge SECOND
Track 3: domain-modules ── (needs T2 base classes) → merge THIRD
Track 4: web-complete ──── (needs T2 API contracts) → merge FOURTH
         │                                              │
         ▼                                              ▼
      T1+T2 start immediately          T3+T4 start immediately (UI/skeleton)
      T3+T4 need T2 merge for full     but need T2 for integration
```

### File Isolation

| Track | Directories (exclusive) | Potential overlap |
|-------|------------------------|-------------------|
| 1. infra-db | `infra/`, `docker-compose*`, `core/migrations/` | - |
| 2. core-engine | `libs/python/`, `core/src/` (engines, auth, middleware) | `pyproject.toml`, `main.py` |
| 3. domain-modules | `core/src/modules/{finance,quest,muse,admin}/` | `main.py` (router registration) |
| 4. web-complete | `workbench/`, `libs/typescript/` | `package.json` |

### Track 1: `feat/infra-db` — Infrastructure + Database

Scope: Docker stack + all database schemas + migration system

### Track 2: `feat/core-engine` — Shared Libs + Auth + Engines

Scope: Python shared lib (BaseService, BaseRepository, BaseRouter) + complete auth system (4 providers) + EventBus + HookBus + RBAC/ABAC + OTel + Session management

### Track 3: `feat/domain-modules` — Business Domain Modules

Scope: Finance, Quest, Muse, Admin modules (backend only, using base classes from T2)

### Track 4: `feat/web-complete` — React Frontend (Complete)

Scope: TypeScript shared lib + all frontend modules + auth UI (login, register, OAuth, Passkey) + shell enhancements + shared components

### Merge Order

1. `feat/infra-db` → main (no conflicts)
2. `feat/core-engine` → main (rebase on main, resolve pyproject.toml)
3. `feat/domain-modules` → main (rebase, resolve main.py router registration)
4. `feat/web-complete` → main (rebase, resolve package.json)

---

## Out of Scope (Future)

- LiveKit/WebRTC (realtime service)
- STT/TTS (media service)
- Plugin marketplace
- Developer tools migration (separate sprint)
- E2E testing
- Production deployment (SigNoz, CI/CD)
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3294ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2560ms
