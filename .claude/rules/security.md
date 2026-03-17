# Security Rules

## Authentication
- Signed cookies via itsdangerous (NOT JWT)
- Sessions stored in Redis: `auth:session:{session_id}`
- Cookie flags: httponly=True, secure=True, samesite=lax, expiry=7d
- Password hashing: Argon2id preferred, bcrypt acceptable. NEVER plaintext.

## Authorization: RBAC + ABAC
- RBAC: admin=`*`, user=`{module}.read`+`{module}.write`, guest=`{module}.read`
- Permission format: `{module}.{action}` (e.g., `finance.write`)
- ABAC layer: owner-only, status-check, rate-limit, time-window
- Apply: `@require_permission("finance.read")` + `enforce_policy("owner-only", ...)`
- Plugin sandbox: effective_permissions = plugin.declared ∩ user.permissions

## Defense-in-Depth (Post-Audit 2026-03-13)
- ALL routes.py MUST have `require_permission()` — Nginx=Layer 1, FastAPI=Layer 2
- Only exceptions: `/status` health checks, public OAuth endpoints
- SQL: f-string with dynamic column/table → MUST whitelist validate; user input → parameterize
- SSRF: URL-accepting endpoints → MUST call `ssrf_guard.validate_url()` (blocks RFC1918/loopback)
- OAuth redirects: validated with `is_safe_url()` (Issue #12)
- Docker ports: ALL use `127.0.0.1:` prefix
- AI prompts: system prompt modification needs `briefing.write` permission

## User Lifecycle
- States: pending → active → suspended / banned
- Only `active` users can login. Suspend/ban clears all sessions.

## Network
- All services bind to 127.0.0.1 — external through Nginx only
- CSRF: SameSite cookies + optional CSRF token
- Inter-service calls are localhost HTTP
