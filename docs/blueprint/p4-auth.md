---
doc_version: 1
content_hash: pending
target_lang: zh-TW
---

> [← 返回優先藍圖總覽](./v2-priorities.md)

# P4：Auth 基礎建設 — Google/GitHub OAuth + 管理系統

### 現況分析

V1 Auth（`avatar-console/backend/auth-service/`）已實現：

| 功能 | V1 狀態 | V2 處置 |
|------|---------|---------|
| Email/Password 登入 | 運作中（pbkdf2_sha256） | 升級為 Argon2id |
| GitHub OAuth | 運作中（authlib + 白名單） | 保留，改寫入 DB |
| Google OAuth | 運作中（OIDC + 白名單） | 保留，改寫入 DB |
| Session 管理 | 運作中（itsdangerous，無過期） | 升級為 Redis-backed + TTL 7天 |
| 使用者管理 | **不存在** | 全新建置 |
| Admin 帳號 | **不存在**（無 seed script） | Seed script + 首位使用者 = admin |

**V1 關鍵缺口**：
1. OAuth 使用者不存入 DB（Session cookie 是唯一狀態）
2. 無 session 過期機制
3. 無 admin 角色、無使用者管理
4. `/register` 僅限 localhost，無正式的註冊審核流

### V2 目標

#### 1. 第一階段就導入 Google + GitHub OAuth

```
瀏覽器 → 登入頁面
  ├── [使用 Google 登入]  → /api/auth/oauth/google → Google OIDC → callback → 建立/連結帳號
  ├── [使用 GitHub 登入]  → /api/auth/oauth/github → GitHub OAuth → callback → 建立/連結帳號
  └── [Email + 密碼]      → /api/auth/login → 驗證密碼 → 建立 session
```

**帳號連結邏輯**：
- 相同 email 的不同 provider → 自動連結到同一個使用者
- OAuth 首次登入 → 建立 `auth.users` + `auth.oauth_accounts` 記錄
- 使用者可在設定頁綁定/解綁 OAuth provider

**DB Schema 擴充**：
```sql
CREATE TABLE auth.oauth_accounts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider    TEXT NOT NULL,             -- 'google', 'github'
    provider_id TEXT NOT NULL,             -- OAuth provider 的 user ID
    email       TEXT,                      -- provider 回傳的 email
    name        TEXT,                      -- provider 回傳的名稱
    avatar_url  TEXT,                      -- 頭像 URL
    raw_data    JSONB,                     -- 完整 OAuth profile 備份
    created_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE(provider, provider_id)
);
```

#### 2. Admin Seed + 初始化

```bash
# 初次啟動自動建立 admin
python -m core.modules.auth.seed

# 邏輯：
# 1. 若 auth.users 表為空 → 建立預設 admin
# 2. 密碼從環境變數 ADMIN_PASSWORD 讀取（必填）
# 3. Email 從環境變數 ADMIN_EMAIL 讀取（必填）
# 4. 狀態直接設為 active，角色設為 admin
# 5. 不硬編碼任何預設密碼
```

**安全原則**：不內建預設帳密。首次部署必須透過環境變數設定。

#### 3. 使用者管理 UI（Admin Module）

| 頁面 | 功能 |
|------|------|
| `/admin/users` | 使用者列表（狀態篩選、搜尋、分頁） |
| `/admin/users/:id` | 使用者詳情（角色、狀態、OAuth 連結、session 歷史） |
| `/admin/users/pending` | 待審核列表（approve / reject 操作） |
| `/admin/audit` | 稽核日誌（登入/登出/角色變更/狀態變更） |

**User Lifecycle UI**：
```
[待審核 Pending] ──(核准)──► [活躍 Active] ──(停權)──► [已停權 Suspended]
                                   │                         │
                                   │                    (解除停權)
                                   │                         │
                                   └────(封鎖)──► [已封鎖 Banned] (永久)
```

#### 4. V1 → V2 遷移

1. **保留 V1 的好設計**：authlib OAuth flow、itsdangerous cookie 簽章、白名單機制
2. **修復缺口**：OAuth 使用者寫入 DB、Session TTL、CSRF 防護、Rate limiting
3. **新增**：帳號連結、Admin seed、使用者管理 UI、RBAC+ABAC 中間件

### 技術架構

```
workbench/src/modules/auth/       ← 登入頁面、OAuth 回調、設定頁
workbench/src/modules/admin/      ← 使用者管理 UI、稽核日誌
core/src/modules/auth/            ← AuthN + AuthZ + Session + OAuth
core/src/modules/admin/           ← 使用者管理 API + 稽核
```

### 遷移策略

1. **Phase A**：建立 auth schema + users/sessions/oauth_accounts 表 + Admin seed script
2. **Phase B**：實作 Email/Password + Google OAuth + GitHub OAuth（參考 V1 authlib 流程）
3. **Phase C**：RBAC+ABAC 中間件 + Session Redis 管理
4. **Phase D**：Admin UI（使用者管理 + 稽核日誌）

### 相關架構文件

- [docs/architecture/auth.md](../architecture/auth.md) — RBAC+ABAC 完整架構設計（DB schema、middleware pipeline、policy engine）
- [v1-feature-inventory.md](./v1-feature-inventory.md) §1 — V1 Auth 完整 API 端點、Session 載荷、已知限制

---

**下一步** → [P5：Finance 記帳系統](./p5-finance.md)
