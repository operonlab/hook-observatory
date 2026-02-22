# Authentication & Authorization Architecture

## Model: Hybrid A+B

**Gateway 負責 AuthN + 平台級 AuthZ，各域服務負責域級 AuthZ。**

```
                        ┌─────────────────────────┐
                        │      Gateway            │
                        │                         │
  Browser ──────────►   │  AuthN: 你是誰？         │
  (Cookie/Token)        │  ├─ 登入/登出/註冊       │
                        │  ├─ Session 管理         │
                        │  └─ 忘記密碼             │
                        │                         │
                        │  AuthZ (平台級):         │
                        │  ├─ user.status 檢查     │
                        │  ├─ Admin 審核/停權      │
                        │  └─ Admin 路由保護       │
                        │                         │
                        │  → X-User-Id            │
                        │  → X-User-Role          │
                        └──────────┬──────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
              ┌──────────┐  ┌──────────┐  ┌──────────┐
              │ Finance  │  │  Quest   │  │   Muse   │
              │          │  │          │  │          │
              │ AuthZ:   │  │ AuthZ:   │  │ AuthZ:   │
              │ 自己的    │  │ 自己的    │  │ 自己的    │
              │ 交易過濾  │  │ 任務過濾  │  │ 內容過濾  │
              └──────────┘  └──────────┘  └──────────┘
```

## Responsibility Split

### Gateway Owns (平台級)

| 類別 | 功能 |
|------|------|
| **AuthN** | 登入、登出、註冊、忘記密碼、Session/Token 管理 |
| **AuthZ** | 用戶狀態檢查 (active/pending/suspended/banned) |
| **AuthZ** | Admin 審核新註冊 |
| **AuthZ** | Admin 停權/解封用戶 |
| **AuthZ** | Admin 路由保護 (`/api/*/admin/*`) |
| **AuthZ** | Rate limiting |

### Each Service Owns (域級)

| 服務 | 域級權限規則 |
|------|-------------|
| Finance | 用戶只能看自己的交易；admin 可查看所有用戶 |
| Quest | 用戶只能管理自己的任務；admin 可分配任務 |
| Muse | 用戶只能編輯自己的 sparks；admin 可管理全域 |
| Research | 用戶只能看自己的報告；admin 可看所有 |

### Trust Contract

各域服務信任 Gateway 傳來的 headers，不需要自己驗證 session：

```
X-User-Id:     UUID  — 已驗證的用戶身份
X-User-Role:   'user' | 'admin' — 平台角色
X-User-Status: 'active' — 一定是 active（否則 Gateway 已擋住）
```

各服務的責任：
1. 讀取 `X-User-Id` → 做資料過濾（只回傳屬於此用戶的資源）
2. 讀取 `X-User-Role` → 決定是否放行 admin 專屬操作
3. **不需要**驗證 session/token（Gateway 已做）
4. **不需要**查詢 `gateway.users` 表（信任 headers）

## User Lifecycle

```
註冊 → pending → (Admin 審核) → active → (正常使用)
                                       → (Admin 停權) → suspended → (Admin 解封) → active
                                       → (Admin 封禁) → banned (永久)
```

### Status Effects

| Status | 能否登入 | 能否呼叫 API | 到達下游服務 |
|--------|---------|-------------|-------------|
| pending | No | No | No |
| active | Yes | Yes | Yes |
| suspended | No (sessions cleared) | No | No |
| banned | No (sessions cleared) | No | No |

## Database Schema (Gateway)

```sql
CREATE SCHEMA gateway;

CREATE TYPE gateway.user_status AS ENUM ('pending', 'active', 'suspended', 'banned');
CREATE TYPE gateway.user_role AS ENUM ('user', 'admin');

CREATE TABLE gateway.users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,  -- bcrypt/argon2 hashed
    name        TEXT NOT NULL,
    status      gateway.user_status NOT NULL DEFAULT 'pending',
    role        gateway.user_role NOT NULL DEFAULT 'user',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by UUID REFERENCES gateway.users(id),
    approved_at TIMESTAMPTZ
);

CREATE TABLE gateway.sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES gateway.users(id) ON DELETE CASCADE,
    token       TEXT UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_sessions_token ON gateway.sessions(token);
CREATE INDEX idx_sessions_user_id ON gateway.sessions(user_id);
```

## Key Flows

### 1. Registration + Admin Approval

```
User  → POST /api/auth/register {email, password, name}
          Gateway → INSERT users (status='pending')
          Gateway → Redis PUBLISH events:gateway:user_registered

Admin → GET /api/auth/admin/users?status=pending
          Gateway → SELECT * FROM users WHERE status='pending'

Admin → POST /api/auth/admin/users/{id}/approve
          Gateway → UPDATE users SET status='active', approved_by, approved_at
          Gateway → Redis PUBLISH events:gateway:user_approved
```

### 2. Login + Authenticated Request

```
User  → POST /api/auth/login {email, password}
          Gateway → Verify password → Create session → Set cookie

User  → GET /api/finance/transactions (Cookie: session)
          Nginx  → auth_request → Gateway /_auth_check
          Gateway → Validate session → Check status=active
          Gateway → Set X-User-Id, X-User-Role headers
          Nginx  → Proxy to Finance service
          Finance → Filter by X-User-Id → Return user's transactions
```

### 3. Admin Suspend User

```
Admin → POST /api/auth/admin/users/{id}/suspend
          Gateway → UPDATE users SET status='suspended'
          Gateway → DELETE FROM sessions WHERE user_id = {id}
          Gateway → Redis PUBLISH events:gateway:user_suspended

Suspended user → Any request
          Gateway → status != active → 403 Forbidden
          (Never reaches any downstream service)
```

## Security Notes

1. **Internal ports never exposed**: Services listen on 127.0.0.1 only. All external traffic goes through Nginx → Gateway.
2. **Header trust boundary**: `X-User-Id` / `X-User-Role` headers are set by Gateway and trusted by services. If a service is accidentally exposed, these headers could be spoofed. Mitigation: firewall + bind to localhost.
3. **Password hashing**: Use argon2 or bcrypt, never store plaintext.
4. **Session expiry**: Default 7 days, configurable. Cleanup via periodic job.
5. **Future expansion**: If roles grow beyond user/admin, introduce RBAC table (`roles`, `permissions`, `role_permissions`) in Gateway schema. Downstream services continue reading `X-User-Role` header — just with more possible values.
