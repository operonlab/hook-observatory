# auth — 身分驗證與授權模組

> Workshop 所有模組的前提基礎。處理身分驗證（AuthN）與授權（AuthZ）。

## 定位

| 屬性 | 值 |
|------|-----|
| **Schema** | `auth` |
| **依賴** | 無（所有模組的基礎） |
| **被依賴** | 所有模組 |
| **MCP** | `workshop-auth`（待建） |
| **V1 參考** | `~/Claude/projects/avatar-console/backend/auth-service/` |

## 功能

### AuthN — 身分驗證

- **Email/Password**：Argon2id 雜湊（V1 為 pbkdf2_sha256，V2 升級）
- **Google OAuth**：OIDC 發現機制，authlib 實作
- **GitHub OAuth**：`read:user user:email` scope
- **帳號連結**：相同 email 不同 provider 自動連結

### AuthZ — 授權

- **RBAC**：admin（`*`）、user（模組級 read/write）、guest（read only）
- **ABAC**：owner-only、status-check、rate-limit、time-window
- **權限格式**：`{module}.{action}`（如 `finance.write`）

### Session 管理

- **機制**：itsdangerous 簽署 cookie + Redis 儲存
- **TTL**：7 天（V1 無過期，V2 修復）
- **Cookie**：`workshop_session`，httponly、secure、samesite=lax

### 使用者生命週期

```
註冊 → pending → (admin 核准) → active → (停權) → suspended
                                      → (封鎖) → banned (永久)
```

只有 `active` 狀態可登入和調用 API。停權/封鎖立即清除所有 session。

## DB Schema

```sql
CREATE SCHEMA auth;

-- 核心表
auth.users              -- 使用者（id, email, password, name, status, role）
auth.oauth_accounts     -- OAuth 綁定（provider, provider_id, email, avatar_url）
auth.sessions           -- 活躍 Session（token, user_id, expires_at）
auth.permissions        -- 角色權限對應（role, permission）
```

## API 端點

| 方法 | 路徑 | 用途 |
|------|------|------|
| POST | `/api/auth/register` | 註冊（狀態為 pending） |
| POST | `/api/auth/login` | Email/Password 登入 |
| POST | `/api/auth/logout` | 登出（清除 session） |
| GET | `/api/auth/me` | 當前使用者資訊 |
| GET | `/api/auth/oauth/{provider}` | 啟動 OAuth 流程 |
| GET | `/api/auth/oauth/{provider}/callback` | OAuth 回調 |

## Admin Seed

首次部署透過環境變數建立 admin：

```bash
ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=... python -m core.modules.auth.seed
```

不硬編碼任何預設帳密。

## 目錄結構

```
core/src/modules/auth/
├── __init__.py       # 模組註冊
├── routes.py         # FastAPI 路由
├── models.py         # SQLAlchemy models（users, oauth_accounts, sessions, permissions）
├── schemas.py        # Pydantic schemas
├── services.py       # 公開 API（其他模組只引用這裡）
├── events.py         # auth.user.registered, auth.user.approved 等
├── deps.py           # get_current_user, require_permission
├── seed.py           # Admin 初始化腳本
└── providers/        # OAuth provider 實作
    ├── google.py
    └── github.py
```

## 參考文件

- [架構設計](../../docs/architecture/auth.md) — RBAC+ABAC 完整設計
- [藍圖](../../docs/blueprint/p4-auth.md) — P4 開發計畫
- [V1 清單](../../docs/blueprint/v1-feature-inventory.md) §1 — V1 Auth 完整記錄
