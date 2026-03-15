# Security Hardening Rules (Post-Lilli Audit 2026-03-13)

## Defense-in-Depth Authentication (鐵律)
- ALL routes.py MUST have `require_permission()` — Nginx auth_request is Layer 1, FastAPI is Layer 2
- New module routes.py template: every endpoint gets `_user: dict = require_permission("module.action")`
- Only exceptions: `/status` health checks, public OAuth endpoints

## SQL Injection Prevention
- f-string SQL with dynamic column/table names → MUST whitelist validate
- User input in SQL intervals/identifiers → MUST parameterize (`:placeholder`)
- `text(f"...")` is a red flag — add `# noqa: S608` only after whitelist validation

## SSRF Protection
- Any endpoint accepting URLs for server-side fetch → MUST call `ssrf_guard.validate_url()`
- Blocked: 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, ::1
- Location: `core/src/shared/ssrf_guard.py`

## Docker Port Binding
- ALL docker-compose ports MUST use `127.0.0.1:` prefix
- Never expose DB/cache/storage ports to 0.0.0.0

## OAuth Redirect Validation
- OAuth redirect URLs MUST be validated with `is_safe_url()` (relative paths or allowed domains only)
- Issue #12 tracks this fix

## AI Prompt Security
- System prompt modification endpoints need `briefing.write` permission (fixed)
- Prompt changes are captured in audit trail automatically via BaseCRUDService
