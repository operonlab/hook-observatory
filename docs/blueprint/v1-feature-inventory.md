# V1 Feature Inventory

Complete documentation of all V1 systems for V2 redesign reference.

## 1. Auth Service (avatar-console)

**Location**: `~/Claude/projects/avatar-console/backend/auth-service/`
**Stack**: Python FastAPI + authlib + itsdangerous + passlib + psycopg2
**Port**: 8790

### Auth Providers

| Provider | Library | Status |
|----------|---------|--------|
| Email/Password | passlib (pbkdf2_sha256) | Working |
| GitHub OAuth | authlib 1.3.0 | Working |
| Google OAuth | authlib 1.3.0 (OIDC) | Working |
| Passkey/WebAuthn | (planned, not implemented) | `.env.example` has vars |

### User Model (PostgreSQL)

```sql
-- users table (local auth only)
CREATE TABLE users (
  id            TEXT PRIMARY KEY,          -- uuid4 hex
  email         TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,             -- pbkdf2_sha256
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- password_reset_tokens
CREATE TABLE password_reset_tokens (
  token       TEXT PRIMARY KEY,            -- secrets.token_urlsafe(32)
  user_id     TEXT REFERENCES users(id),
  expires_at  TIMESTAMPTZ,                 -- +30 min
  used_at     TIMESTAMPTZ,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

**Critical gap**: OAuth users NOT stored in DB. Session cookie is the only state.

### Session Management

- `itsdangerous.URLSafeSerializer` (no expiry)
- Cookie: `avator_session`, httponly, secure, samesite=lax
- No max_age (session cookie = browser lifetime)
- OAuth state stored in separate Starlette SessionMiddleware

### Session Payload

```python
{"user": {"id": "github:12345", "email": "x@y.com", "method": "github"}}
```

### API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | /api/auth/register | Create local account (localhost only) |
| POST | /api/auth/login | Password login |
| GET/POST | /api/auth/logout | Logout (multiple formats) |
| GET | /api/auth/check | nginx auth_request probe |
| POST | /api/auth/forgot | Password reset request (disabled: 501) |
| POST | /api/auth/reset | Password reset with token |
| GET | /auth/login/github | GitHub OAuth initiate |
| GET | /auth/callback/github | GitHub OAuth callback |
| GET | /auth/login/google | Google OAuth initiate |
| GET | /auth/callback/google | Google OAuth callback |

### OAuth Config

- GitHub: `read:user user:email` scopes, allowlist via `ALLOWED_GITHUB_USERS`
- Google: `openid email profile` scopes, OIDC discovery, allowlist via `ALLOWED_GOOGLE_EMAILS`
- Both use authlib `authorize_redirect` → `authorize_access_token` flow

### Frontend (Server-rendered HTML)

- Login page: OAuth buttons + password form
- Register page: localhost only
- Apps page: grid of protected apps
- Not a SPA — server-rendered Jinja2 templates

### Known Limitations

1. OAuth users not in DB (no user management possible)
2. No session expiry (browser-lifetime only)
3. Forgot password disabled (SMTP configured but 501)
4. No WebAuthn despite .env.example having vars
5. No CSRF protection
6. No rate limiting
7. Register restricted to localhost

---

## 2. Developer Tools

### 2.1 disk-report

**Location**: `~/.claude/data/disk-report/`
**Stack**: Python FastAPI + Jinja2, port 9527
**Features**: Disk scan (du/df/apfs), AI analysis (Gemini/Claude), delete/clean operations
**Frontend**: Full dashboard (5 tabs: overview, large files, old files, caches, reports)
**Storage**: Pure filesystem (reports as markdown)
**Launch**: LaunchAgent (daily 03:30 report generation)
**API**: 8 endpoints (summary, scan, reports, delete, clean-cache, empty-trash)
**Security**: Protected path validation (system dirs, .claude, .ssh blocked)

### 2.2 cost-server (LLM Usage)

**Location**: `~/.claude/data/cost-server/`
**Stack**: Node.js (zero deps), Unix socket `~/.claude/cost-server.sock`
**Features**: Per-session cost tracking, daily rollover, stale session filtering
**Storage**: `state.json` (atomic write via rename)
**Launch**: LaunchAgent (auto-restart)
**API**: 3 endpoints (POST /update, GET /stats, GET /health)

### 2.3 tmux-webui

**Location**: `~/Claude/projects/tmux-webui/`
**Stack**: Python (aiohttp or FastAPI), single file server.py
**Features**: List sessions/panes/windows, send keys, web-based control
**Frontend**: Browser control interface

### 2.4 kas-memory

**Location**: `~/Claude/projects/kas-memory/`
**Stack**: TypeScript MCP Server (@modelcontextprotocol/sdk)
**Features**: Hybrid search (BM25 + cosine + RRF), auto-extract from sessions, tag system, embedding (Ollama/OpenAI), knowledge promotion, KAS profile
**Storage**: Markdown files (memories/), JSON (embeddings, tags, profile)
**Tools**: 9 MCP tools + 2 resources
**Hooks**: extract.sh (SessionEnd), recall.sh (UserPromptSubmit)

### 2.5 session-redactor

**Location**: `~/Claude/projects/session-redactor/`
**Stack**: Python FastAPI (sub-router of V1 platform)
**Features**: 20 regex patterns, JSON-aware recursive redaction, daily sweep
**Storage**: SQLite (file tracking, dedup via inode)
**API**: 4 endpoints (status, scan, history, history by session)

### 2.6 observability

**Location**: `~/Claude/projects/claude-code-hooks-multi-agent-observability/`
**Stack**: Bun + SQLite (server), Vue 3 + Vite + Tailwind (client)
**Ports**: 4000 (server) + 5173 (client)
**Features**: 12 hook event types, real-time WebSocket dashboard, HITL, agent swim lanes, theme system
**Frontend**: Full Vue 3 dashboard with live pulse chart, event timeline, filter panel
**Hooks**: 12 Python scripts (pre/post tool use, session lifecycle, etc.)

---

## 3. V1 Apps (from auth /apps page)

| App | Path | Description |
|-----|------|------------|
| Avatar Console | /console/ | Chat interface (Vue SPA) |
| Finance | /finance | Accounting app |
| Ideas | /ideas | Knowledge graph |
| OpenClaw | /openclaw/ | (unknown) |
| Terminal | /terminal/ | Web terminal |
| Disk Report | /apps/disk-report/ | Disk analysis |
| Skill Galaxy | /apps/galaxy/ | Skill visualization |
| Daily Briefing | /apps/briefing/ | Daily intel digest |

---

## 4. Common Patterns Across V1

### What Works (Keep)
- authlib for OAuth (clean API, OIDC discovery)
- itsdangerous for cookie signing (simple, secure)
- LaunchAgent for background services (macOS native)
- Markdown as storage format (kas-memory)
- Dark theme (consistent across tools)

### What's Broken (Fix in V2)
- OAuth users not in DB → V2: unified user table + oauth_accounts
- No session expiry → V2: DB-backed sessions with TTL
- No WebAuthn → V2: py_webauthn + @simplewebauthn/browser
- No CSRF protection → V2: double-submit cookie or SameSite strict
- No rate limiting → V2: slowapi + Redis backend
- Scattered tools → V2: unified project structure
- No code reuse → V2: shared libs (Python + TypeScript)
- No observability → V2: OpenTelemetry + LGTM

### What's Missing (Add in V2)
- Account linking (same email, multiple providers)
- Admin user management
- Multi-provider auth abstraction
- Centralized event bus
- Plugin system
- RBAC+ABAC enforcement on every route
