---
doc_version: 1
content_hash: aece66bc
source_version: 1
translated_at: 2026-02-23
---

# Authentication & Authorization Architecture

## Model: RBAC + ABAC Hybrid

The auth module (part of Core Monolith) handles both authentication and authorization using a layered permission model.

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
| `admin` | `*` (all) | Full platform access |
| `user` | `finance.read`, `finance.write`, `quest.read`, `quest.write`, `muse.read`, `muse.write` | Standard active user |
| `guest` | `finance.read`, `quest.read`, `muse.read` | Read-only access |

### Permission Format

```
{module}.{action}

Examples:
  finance.read        Read financial data
  finance.write       Create/update financial records
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
| `time-window` | `now() within allowed_hours` | Admin operations only during business hours |

### ABAC Check

```python
from core.modules.auth.policies import enforce_policy

 @router.put("/api/finance/transactions/{txn_id}")
 @require_permission("finance.write")
async def update_transaction(txn_id: str, user: AuthUser = Depends(get_current_user)):
    txn = await get_transaction(txn_id)
    enforce_policy("owner-only", user=user, resource=txn)  # raises 403 if not owner
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

## Plugin Permission Isolation

Plugins run with the **intersection** of their declared permissions and the current user's permissions:

```
effective_permissions = plugin.manifest.permissions ∩ user.permissions
```

A plugin declaring `["finance.read", "quest.write"]` for an admin user gets both. For a guest user, it only gets `finance.read` (since guests lack `quest.write`).

See [Plugin System](./plugin-system.md) for manifest format.

## Session Management

### Signed Cookie (itsdangerous)

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

**Why signed cookies over JWT:**
- Server-side revocation (just invalidate the session record)
- No token size bloat in every request
- Simple implementation, fewer security pitfalls

### Session Storage

Active sessions are tracked in Redis for fast validation and revocation:

```
auth:session:{session_id} → {user_id, role, created_at, expires_at}
```

## User Lifecycle

```
Register → pending → (Admin approval) → active → (normal use)
                                       → (Admin suspend) → suspended → (Admin unsuspend) → active
                                       → (Admin ban) → banned (permanent)
```

### Status Effects

| Status | Can Login | Can Call API | Reaches Modules |
|--------|-----------|-------------|-----------------|
| pending | No | No | No |
| active | Yes | Yes | Yes |
| suspended | No (sessions cleared) | No | No |
| banned | No (sessions cleared) | No | No |

## Database Schema (auth module)

```sql
CREATE SCHEMA auth;

CREATE TYPE auth.user_status AS ENUM ('pending', 'active', 'suspended', 'banned');
CREATE TYPE auth.user_role AS ENUM ('guest', 'user', 'admin');

CREATE TABLE auth.users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,  -- argon2 hashed
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
User  → POST /api/auth/register {email, password, name}
          Auth module → INSERT users (status='pending')
          EventBus → publish("auth.user.registered", {user_id})

Admin → GET /api/admin/users?status=pending
Admin → POST /api/admin/users/{id}/approve
          Auth module → UPDATE status='active'
          EventBus → publish("auth.user.approved", {user_id})
```

### 2. Login + Authenticated Request

```
User  → POST /api/auth/login {email, password}
          Auth module → Verify password → Create session → Set signed cookie

User  → GET /api/finance/transactions (Cookie: session)
          Auth middleware → Validate signed cookie
          Auth middleware → Load user, check status=active
          Auth middleware → Check RBAC permission (finance.read)
          Finance module → Filter by user_id → Return transactions
```

### 3. Admin Suspend User

```
Admin → POST /api/admin/users/{id}/suspend
          Auth module → UPDATE status='suspended'
          Auth module → DELETE sessions WHERE user_id={id}
          EventBus → publish("auth.user.suspended", {user_id})
```

## Security Notes

1. **Password hashing**: Argon2id (preferred) or bcrypt. Never store plaintext.
2. **Cookie security**: `httponly=True`, `secure=True`, `samesite=lax`.
3. **Session expiry**: Default 7 days, configurable. Periodic cleanup via background task.
4. **Internal ports**: Services bind to `127.0.0.1`. All external traffic goes through Nginx.
5. **CSRF protection**: SameSite cookies + optional CSRF token for mutation endpoints.

## Future: OAuth Providers

Planned OAuth integration (Google, GitHub) for social login:

```
Browser → /api/auth/oauth/google → redirect to Google
Google  → /api/auth/oauth/google/callback → Auth module creates/links user
```

OAuth will supplement password auth, not replace it. Both methods create the same session format.
