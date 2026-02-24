---
doc_version: 1
content_hash: 68a8fc10
source_version: 1
target_lang: en
translated_at: 2026-02-24
source_hash: 13c1a010
source_lang: zh-TW
---

# V1 Feature List

Complete documentation of all V1 systems for V2 refactoring reference.

## 1. Authentication Service (avatar-console)

**Location**: `~/Claude/projects/avatar-console/backend/auth-service/`
**Tech Stack**: Python FastAPI + authlib + itsdangerous + passlib + psycopg2
**Port**: 8790

### Authentication Providers

| Provider | Library | Status |
|----------|---------|--------|
| Email/Password | passlib (pbkdf2_sha256) | Operational |
| GitHub OAuth | authlib 1.3.0 | Operational |
| Google OAuth | authlib 1.3.0 (OIDC) | Operational |
| Passkey/WebAuthn | (Planned, not yet implemented) | Variables exist in `.env.example` |

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

**Key Gap**: OAuth users are not stored in the database. The session cookie is the only state.

### Session Management

- `itsdangerous.URLSafeSerializer` (no expiration)
- Cookie: `avator_session`, httponly, secure, samesite=lax
- No max_age (session cookie = browser lifetime)
- OAuth state is stored in a separate Starlette SessionMiddleware

### Session Payload

```python
{"user": {"id": "github:12345", "email": "x @y.com", "method": "github"}}
```

### API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | /api/auth/register | Create local account (localhost only) |
| POST | /api/auth/login | Password login |
| GET/POST | /api/auth/logout | Logout (multiple formats) |
| GET | /api/auth/check | nginx auth_request probe |
| POST | /api/auth/forgot | Password reset request (disabled: 501) |
| POST | /api/auth/reset | Reset password with token |
| GET | /auth/login/github | Initiate GitHub OAuth |
| GET | /auth/callback/github | GitHub OAuth callback |
| GET | /auth/login/google | Initiate Google OAuth |
| GET | /auth/callback/google | Google OAuth callback |

### OAuth Configuration

- GitHub: `read:user user:email` scope, filtered by `ALLOWED_GITHUB_USERS` allowlist
- Google: `openid email profile` scope, OIDC discovery, filtered by `ALLOWED_GOOGLE_EMAILS` allowlist
- Both use authlib's `authorize_redirect` → `authorize_access_token` flow

### Frontend (Server-Side Rendered HTML)

- Login page: OAuth buttons + password form
- Register page: localhost only
- Apps page: Grid view of protected applications
- Not a Single-Page Application (SPA) — uses server-side rendered Jinja2 templates

### Known Limitations

1. OAuth users are not in the database (no user management)
2. No session expiration (browser lifetime only)
3. Forgot password feature is disabled (SMTP configured but returns 501)
4. WebAuthn is not implemented despite variables in .env.example
5. Lacks CSRF protection
6. Lacks rate limiting
7. Registration is restricted to localhost

---

## 2. Developer Tools

### 2.1 disk-report

**Location**: `~/.claude/data/disk-report/`
**Tech Stack**: Python FastAPI + Jinja2, Port 9527
**Features**: Disk scanning (du/df/apfs), AI analysis (Gemini/Claude), delete/cleanup operations
**Frontend**: Full dashboard (5 tabs: Overview, Large Files, Old Files, Caches, Reports)
**Storage**: Pure filesystem (reports are in markdown format)
**Startup**: LaunchAgent (generates report daily at 03:30)
**API**: 8 endpoints (summary, scan, report, delete, clean cache, empty trash)
**Security**: Protected path validation (blocks system dirs, .claude, .ssh)

### 2.2 cost-server (LLM Usage)

**Location**: `~/.claude/data/cost-server/`
**Tech Stack**: Node.js (no dependencies), Unix socket `~/.claude/cost-server.sock`
**Features**: Per-session cost tracking, daily changelog, expired session filtering
**Storage**: `state.json` (atomic writes via rename)
**Startup**: LaunchAgent (auto-restarts)
**API**: 3 endpoints (POST /update, GET /stats, GET /health)

### 2.3 tmux-webui

**Location**: `~/Claude/projects/tmux-webui/`
**Tech Stack**: Python (aiohttp or FastAPI), single-file server.py
**Features**: List sessions/panes/windows, send keys, web-based control
**Frontend**: Browser-based control interface

### 2.4 kas-memory

**Location**: `~/Claude/projects/kas-memory/`
**Tech Stack**: TypeScript MCP Server (@modelcontextprotocol/sdk)
**Features**: Hybrid search (BM25 + cosine similarity + RRF), auto-extraction from sessions, tag system, embeddings (Ollama/OpenAI), knowledge promotion, KAS profile
**Storage**: Markdown files (memories/), JSON (embeddings, tags, profile)
**Tools**: 9 MCP tools + 2 resources
**Hooks**: extract.sh (session end), recall.sh (user prompt submission)

### 2.5 session-redactor

**Location**: `~/Claude/projects/session-redactor/`
**Tech Stack**: Python FastAPI (sub-router on V1 platform)
**Features**: 20 regex patterns, recursive redaction for JSON, daily cleanup
**Storage**: SQLite (file tracking, deduplication via inode)
**API**: 4 endpoints (status, scan, history, query history by session)

### 2.6 Observability

**Location**: `~/Claude/projects/claude-code-hooks-multi-agent-observability/`
**Tech Stack**: Bun + SQLite (server), Vue 3 + Vite + Tailwind (client)
**Ports**: 4000 (server) + 5173 (client)
**Features**: 12 hook event types, real-time WebSocket dashboard, Human-in-the-Loop (HITL), agent swimlanes, theming system
**Frontend**: Full Vue 3 dashboard with real-time pulse graph, event timeline, filtering panel
**Hooks**: 12 Python scripts (before/after tool use, session lifecycle, etc.)

---

## 3. V1 Applications (from auth /apps page)

| Application | Path | Description |
|-----|------|------------|
| Avatar Console | /console/ | Chat interface (Vue SPA) |
| Finance | /finance | Finance tracking app |
| Ideas | /ideas | Knowledge graph |
| OpenClaw | /openclaw/ | (Unknown) |
| Terminal | /terminal/ | Web terminal |
| Disk Report | /apps/disk-report/ | Disk analysis |
| Skill Galaxy | /apps/galaxy/ | Skill visualization |
| Daily Briefing | /apps/briefing/ | Daily intelligence briefing |

---

## 4. V1 Cross-System Common Patterns

### What Worked Well (To Keep)
- Using authlib for OAuth (clean API, supports OIDC discovery)
- Using itsdangerous for cookie signing (simple and secure)
- Using LaunchAgent for background services (native to macOS)
- Using Markdown as a storage format (kas-memory)
- Dark theme (consistent across tools)

### Areas for Improvement (To Fix in V2)
- OAuth users not stored in DB → V2: Unified user table + oauth_accounts
- No session expiration → V2: DB-backed sessions with TTL
- Lack of WebAuthn → V2: Use py_webauthn + @simplewebauthn/browser
- Lack of CSRF protection → V2: Use double-submit cookie or SameSite strict
- Lack of rate limiting → V2: Use slowapi + Redis backend
- Scattered tools → V2: Unified project structure
- Lack of code reuse → V2: Shared libraries (Python + TypeScript)
- Lack of observability → V2: Use OpenTelemetry + LGTM

### Missing Features (To Add in V2)
- Account linking (same email, multiple providers)
- Admin user management
- Multi-provider auth abstraction
- Centralized event bus
- Plugin system
- RBAC+ABAC enforcement per route
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3162ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2222ms
