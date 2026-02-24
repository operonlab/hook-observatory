---
doc_version: 2
content_hash: 4a697601
source_version: 1
target_lang: zh-TW
translated_at: 2026-02-23
---

# 身分驗證與授權架構

## 模型：RBAC + ABAC 混合模式

auth 模組（Core Monolith 的一部分）使用分層權限模型處理身分驗證（authentication）與授權（authorization）。

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
                    │  │ finance │ │  taskflow  │ │  ideagraph  │ │
                    │  │ routes  │ │ routes  │ │ routes │ │
                    │  └─────────┘ └─────────┘ └────────┘ │
                    └──────────────────────────────────────┘
```

## RBAC 層：基於角色的存取控制 (Role-Based Access Control)

### 角色與權限

| 角色 | 權限 | 描述 |
|------|------------|-------------|
| `admin` | `*` (全部) | 全平台存取權限 |
| `user` | `finance.read`, `finance.write`, `taskflow.read`, `taskflow.write`, `ideagraph.read`, `ideagraph.write` | 標準啟用使用者 |
| `guest` | `finance.read`, `taskflow.read`, `ideagraph.read` | 唯讀存取權限 |

### 權限格式

```
{module}.{action}

範例：
  finance.read        讀取財務數據
  finance.write       建立/更新財務紀錄
  taskflow.read          查看任務 (quests)
  taskflow.write         建立/管理任務 (quests)
  admin.users         管理使用者
  admin.audit         查看稽核日誌 (audit logs)
```

### RBAC 檢查

```python
from core.modules.auth.permissions import require_permission

 @router.get("/api/finance/transactions")
 @require_permission("finance.read")
async def list_transactions(user: AuthUser = Depends(get_current_user)):
    ...
```

## ABAC 層：基於屬性的存取控制 (Attribute-Based Access Control)

ABAC 策略在 RBAC 之上增加了動態的、上下文感知的檢查。

### 策略類型

| 策略 | 規則 | 範例 |
|--------|------|---------|
| `owner-only` | `resource.owner_id == user.id` | 使用者僅能編輯自己的交易 |
| `status-check` | `resource.status in allowed_statuses` | 無法修改已歸檔的任務 (quests) |
| `rate-limit` | `user.request_count < limit` | 每分鐘最多 100 次 API 調用 |
| `time-window` | `now() within allowed_hours` | 僅在營業時間內進行管理員操作 |

### ABAC 檢查

```python
from core.modules.auth.policies import enforce_policy

 @router.put("/api/finance/transactions/{txn_id}")
 @require_permission("finance.write")
async def update_transaction(txn_id: str, user: AuthUser = Depends(get_current_user)):
    txn = await get_transaction(txn_id)
    enforce_policy("owner-only", user=user, resource=txn)  # 若非所有者則拋出 403
    ...
```

### 策略引擎

```python
class PolicyEngine:
    """評估 ABAC 策略與請求上下文。"""

    def evaluate(self, policy_name: str, context: PolicyContext) -> bool:
        policy = self.policies[policy_name]
        return policy.check(
            user=context.user,
            resource=context.resource,
            action=context.action,
            environment=context.environment,  # 時間、IP 等
        )
```

### 插件權限隔離

插件執行時的有效權限 = 插件宣告權限 ∩ 使用者權限。詳見 [Plugin System](./plugin-system.md#權限隔離)。

## 會話管理 (Session Management)

### 已簽署 Cookie (itsdangerous)

會話透過 `itsdangerous` 使用**已簽署 Cookie (signed cookies)**：

```python
from itsdangerous import URLSafeTimedSerializer

serializer = URLSafeTimedSerializer(secret_key=settings.secret_key)

# 建立會話
token = serializer.dumps({"user_id": str(user.id), "role": user.role})
response.set_cookie("session", token, httponly=True, secure=True, samesite="lax")

# 驗證會話
data = serializer.loads(token, max_age=604800)  # 7 天
```

**為什麼選擇已簽署 Cookie 而非 JWT：**
- 伺服器端撤銷（只需使會話紀錄失效）
- 每次請求中不會有巨大的 Token 體積
- 實作簡單，安全性陷阱較少

### 會話儲存 (Session Storage)

活躍會話會追蹤於 Redis 中，以便進行快速驗證與撤銷：

```
auth:session:{session_id} → {user_id, role, created_at, expires_at}
```

## 使用者生命週期 (User Lifecycle)

```
註冊 (Register) → 待定 (pending) → (管理員核准) → 活躍 (active) → (正常使用)
                                       → (管理員停權) → 已停權 (suspended) → (管理員解除停權) → 活躍 (active)
                                       → (管理員封鎖) → 已封鎖 (banned) (永久)
```

### 狀態影響

| 狀態 | 可登入 | 可調用 API | 抵達模組 |
|--------|-----------|-------------|-----------------|
| pending | 否 | 否 | 否 |
| active | 是 | 是 | 是 |
| suspended | 否（清除會話） | 否 | 否 |
| banned | 否（清除會話） | 否 | 否 |

## 資料庫綱要 (auth module)

```sql
CREATE SCHEMA auth;

CREATE TYPE auth.user_status AS ENUM ('pending', 'active', 'suspended', 'banned');
CREATE TYPE auth.user_role AS ENUM ('guest', 'user', 'admin');

CREATE TABLE auth.users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,  -- argon2 加密雜湊
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

## 關鍵流程

### 1. 註冊 + 管理員核准

```
使用者  → POST /api/auth/register {email, password, name}
          Auth 模組 → INSERT users (status='pending')
          EventBus → publish("auth.user.registered", {user_id})

管理員 → GET /api/admin/users?status=pending
管理員 → POST /api/admin/users/{id}/approve
          Auth 模組 → UPDATE status='active'
          EventBus → publish("auth.user.approved", {user_id})
```

### 2. 登入 + 已驗證請求

```
使用者  → POST /api/auth/login {email, password}
          Auth 模組 → 驗證密碼 → 建立會話 → 設定已簽署 Cookie

使用者  → GET /api/finance/transactions (Cookie: session)
          Auth 中間件 → 驗證已簽署 Cookie
          Auth 中間件 → 載入使用者，檢查 status=active
          Auth 中間件 → 檢查 RBAC 權限 (finance.read)
          Finance 模組 → 依 user_id 過濾 → 回傳交易紀錄
```

### 3. 管理員停權使用者

```
管理員 → POST /api/admin/users/{id}/suspend
          Auth 模組 → UPDATE status='suspended'
          Auth 模組 → DELETE sessions WHERE user_id={id}
          EventBus → publish("auth.user.suspended", {user_id})
```

## 安全注意事項

1. **密碼雜湊 (Password hashing)**：Argon2id（偏好）或 bcrypt。絕不儲存明文。
2. **Cookie 安全**：`httponly=True`、`secure=True`、`samesite=lax`。
3. **會話過期**：預設 7 天，可配置。透過背景任務進行定期清理。
4. **內部連接埠**：服務綁定至 `127.0.0.1`。所有外部流量均通過 Nginx。
5. **CSRF 防護**：SameSite cookies + 針對變動性端點的選用 CSRF token。

## OAuth 提供者（第一階段導入）

Google 與 GitHub OAuth 已確定於第一階段（P4）導入，非未來規劃。

```
瀏覽器 → /api/auth/oauth/{provider} → 重新導向至 Provider
Provider → /api/auth/oauth/{provider}/callback → Auth 模組建立/連結使用者
```

**帳號連結**：相同 email 的不同 provider 自動連結到同一個使用者。

```sql
CREATE TABLE auth.oauth_accounts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider    TEXT NOT NULL,             -- 'google', 'github'
    provider_id TEXT NOT NULL,             -- OAuth provider 的 user ID
    email       TEXT,
    name        TEXT,
    avatar_url  TEXT,
    raw_data    JSONB,
    created_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE(provider, provider_id)
);
```

OAuth 作為密碼驗證的補充而非取代。兩種方式都會建立相同的會話格式。

詳見 [P4：Auth 基礎建設](../blueprint/p4-auth.md)。
