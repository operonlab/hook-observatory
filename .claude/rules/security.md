# Security Rules

## Authentication
- Signed cookies via itsdangerous (NOT JWT)
- Sessions stored in Redis: `auth:session:{session_id}`
- Cookie flags: httponly=True, secure=True, samesite=lax
- Session expiry: 7 days default
- Password hashing: Argon2id preferred, bcrypt acceptable. NEVER plaintext.

## Authorization: RBAC + ABAC
- RBAC layer: role → permission set
  - admin: `*` (all), user: `{module}.read` + `{module}.write`, guest: `{module}.read` only
- Permission format: `{module}.{action}` (e.g., `finance.write`)
- ABAC layer on top: owner-only, status-check, rate-limit, time-window
- Apply: `@require_permission("finance.read")` + `enforce_policy("owner-only", ...)`

## User Lifecycle
- States: pending → active → suspended / banned
- Only `active` users can login and call APIs
- Suspend/ban immediately clears all sessions

## Plugin Permission Sandbox
- effective_permissions = plugin.declared ∩ current_user.permissions
- Plugins CANNOT access undeclared modules
- Plugins CANNOT escalate beyond the invoking user

## Network
- All services bind to 127.0.0.1 — external traffic only through Nginx
- CSRF: SameSite cookies + optional CSRF token for mutations
- All inter-service calls (Core → Media, Core → Realtime) are localhost HTTP
