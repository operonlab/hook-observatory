---
doc_version: 2
content_hash: 4a697601
source_version: 1
target_lang: en
translated_at: 2026-02-24
source_hash: 4a697601
source_lang: zh-TW
---

# Authentication and Authorization Architecture

## Model: Hybrid RBAC + ABAC

The `auth` module (part of the Core Monolith) handles authentication and authorization using a layered permissions model.

```
                    ┌──────────────────────────────────────┐
                    │           Core Monolith               │
                    │                                      │
  Browser ────────► │  Auth Module                         │
  (Signed Cookie)   │  ├─ AuthN: Session validation        │
                    │  ├─ RBAC: role → permission set      │
                    │  └─ ABAC: dynamic attribute policies  │
                    │                                      │
                    │  Middleware Pipeline:                 │
                    │  1. Validate session (signed cookie)  │
                    │  2. Load user + role + permissions    │
                    │  3. Check RBAC (static permissions)   │
                    │  4. Check ABAC (dynamic policies)     │
                    │  5. Forward to route handler          │
                    │                                      │
                    │  ┌─────────┐ ┌─────────┐ ┌────────┐ │
                    │  │ finance │ │  quest  │ │  muse  │ │
                    │  │ routes  │ │ routes  │ │ routes │ │
                    │  └─────────┘ └─────────┘ └────────┘ │
                    └──────────────────────────────────────┘
```

## RBAC Layer: Role-Based Access Control

### Roles and Permissions

| Role | Permissions | Description |
|------|------------|-------------|
| `admin` | `*` (All) | Full platform access |
| `user` | `finance.read`, `finance.write`, `quest.read`, `quest.write`, `muse.read`, `muse.write` | Standard activated user |
| `guest` | `finance.read`, `quest.read`, `muse.read` | Read-only access |

### Permission Format

```
{module}.{action}

Examples:
  finance.read        Read finance data
  finance.write       Create/update finance records
  quest.read          View quests
  quest.write         Create/manage quests
  admin.users         Manage users
  admin.audit         View audit logs
```

### RBAC Check

```python
from core.modules.auth.permissions import require_permission

 @router.get("/api/finance/transactions")
 @require_permission("finance.read")
async def list_transactions(user: AuthUser = Depends(get_current_user)):
    ...
```

## ABAC Layer: Attribute-Based Access Control

ABAC policies add dynamic, context-aware checks on top of RBAC.

### Policy Types

| Policy | Rule | Example |
|--------|------|---------|
| `owner-only` | `resource.owner_id == user.id` | User can only edit their own transactions |
| `status-check` | `resource.status in allowed_statuses` | Cannot modify archived quests |
| `rate-limit` | `user.request_count < limit` | Max 100 API calls per minute |
| `time-window` | `now() within allowed_hours` | Admin actions only during business hours |

### ABAC Check

```python
from core.modules.auth.policies import enforce_policy

 @router.put("/api/finance/transactions/{txn_id}")
 @require_permission("finance.write")
async def update_transaction(txn_id: str, user: AuthUser = Depends(get_current_user)):
    txn = await get_transaction(txn_id)
    enforce_policy("owner-only", user=user, resource=txn)  # Throws 403 if not owner
    ...
```

### Policy Engine

```python
class PolicyEngine:
    """Evaluates ABAC policies against request context."""

    def evaluate(self, policy_name: str, context: PolicyContext) -> bool:
        policy = self.policies[policy_name]
        return policy.check(
            user=context.user,
            resource=context.resource,
            action=context.action,
            environment=context.environment,  # time, IP, etc.
        )
```

### Plugin Permission Isolation

Effective permissions during plugin execution = declared plugin permissions ∩ user permissions. See [Plugin System](./plugin-system.md#權限隔離) for details.

## Session Management

### Signed Cookies (itsdangerous)

Sessions use **signed cookies** via `itsdangerous`:

```python
from itsdangerous import URLSafeTimedSerializer

serializer = URLSafeTimedSerializer(secret_key=settings.secret_key)

# Create session
token = serializer.dumps({"user_id": str(user.id), "role": user.role})
response.set_cookie("session", token, httponly=True, secure=True, samesite="lax")

# Validate session
data = serializer.loads(token, max_age=604800)  # 7 days
```

**Why Signed Cookies over JWT:**
- Server-side revocation (just invalidate the session record)
- No giant token size in every request
- Simpler implementation, fewer security pitfalls

### Session Storage

Active sessions are tracked in Redis for fast validation and revocation:

```
auth:session:{session_id} → {user_id, role, created_at, expires_at}
```

## User Lifecycle

```
Register → pending → (Admin approval) → active → (Normal usage)
                                    → (Admin suspension) → suspended → (Admin unsuspension) → active
                                    → (Admin ban) → banned (permanent)
```

### Status Impact

| Status | Can Login | Can Call API | Reaches Module |
|--------|-----------|-------------|-----------------|
| pending | No | No | No |
| active | Yes | Yes | Yes |
| suspended | No (clears session) | No | No |
| banned | No (clears session) | No | No |

## Database Schema (auth module)

```sql
CREATE SCHEMA auth;

CREATE TYPE auth.user_status AS ENUM ('pending', 'active', 'suspended', 'banned');
CREATE TYPE auth.user_role AS ENUM ('guest', 'user', 'admin');

CREATE TABLE auth.users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,  -- argon2 encrypted hash
    name        TEXT NOT NULL,
    status      auth.user_status NOT NULL DEFAULT 'pending',
    role        auth.user_role NOT NULL DEFAULT 'user',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by UUID REFERENCES auth.users(id),
    approved_at TIMESTAMPTZ
);

CREATE TABLE auth.permissions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role        auth.user_role NOT NULL,
    permission  TEXT NOT NULL,
    UNIQUE(role, permission)
);

CREATE TABLE auth.sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    token       TEXT UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);
```

## Key Flows

### 1. Registration + Admin Approval

```
User → POST /api/auth/register {email, password, name}
       Auth Module → INSERT users (status='pending')
       EventBus → publish("auth.user.registered", {user_id})

Admin → GET /api/admin/users?status=pending
Admin → POST /api/admin/users/{id}/approve
        Auth Module → UPDATE status='active'
        EventBus → publish("auth.user.approved", {user_id})
```

### 2. Login + Authenticated Request

```
User → POST /api/auth/login {email, password}
       Auth Module → Verify password → Create session → Set signed cookie

User → GET /api/finance/transactions (Cookie: session)
       Auth Middleware → Validate signed cookie
       Auth Middleware → Load user, check status=active
       Auth Middleware → Check RBAC permission (finance.read)
       Finance Module → Filter by user_id → Return transactions
```

### 3. Admin Suspends User

```
Admin → POST /api/admin/users/{id}/suspend
        Auth Module → UPDATE status='suspended'
        Auth Module → DELETE sessions WHERE user_id={id}
        EventBus → publish("auth.user.suspended", {user_id})
```

## Security Considerations

1.  **Password Hashing**: Argon2id (preferred) or bcrypt. Never store in plaintext.
2.  **Cookie Security**: `httponly=True`, `secure=True`, `samesite=lax`.
3.  **Session Expiration**: 7-day default, configurable. Periodically cleaned by a background job.
4.  **Internal Ports**: Services bind to `127.0.0.1`. All external traffic goes through Nginx.
5.  **CSRF Protection**: SameSite cookies + optional CSRF tokens for mutating endpoints.

## Future: OAuth Providers

Planning to integrate OAuth (Google, GitHub) for social login:

```
Browser → /api/auth/oauth/google → Redirect to Google
Google  → /api/auth/oauth/google/callback → Auth module creates/links user
```

OAuth will supplement, not replace, password authentication. Both methods will create the same session format.
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2520ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2387ms
