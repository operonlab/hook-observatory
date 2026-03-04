---
doc_version: 1
content_hash: 68a8fc10
source_version: 1
target_lang: zh-TW
translated_at: 2026-02-23
---

# V1 功能清單

> **注意**：本文件為 V1 歷史紀錄。文中所有 `~/Claude/` 路徑為 V1 時期的原始位置，已遷移至 V2 `~/workshop/` 對應目錄：
> - `~/Claude/projects/avatar-console/` → `~/workshop/core/src/modules/auth/`
> - `~/Claude/projects/tmux-webui/` → `~/workshop/stations/tmux-webui/`
> - `~/Claude/projects/kas-memory/` → `~/workshop/core/src/modules/memvault/` + `~/workshop/mcp/memvault/`
> - `~/Claude/projects/session-redactor/` → `~/workshop/stations/session-redactor/`
> - `~/Claude/projects/claude-code-hooks-multi-agent-observability/` → `~/workshop/vendor/observability/`

所有 V1 系統的完整文件，供 V2 重構參考。

## 1. 身份驗證服務 (avatar-console)

**位置**: `~/Claude/projects/avatar-console/backend/auth-service/`
**技術棧**: Python FastAPI + authlib + itsdangerous + passlib + psycopg2
**埠號**: 8790

### 身份驗證提供商

| 提供商 | 函式庫 | 狀態 |
|----------|---------|--------|
| Email/Password | passlib (pbkdf2_sha256) | 運作中 |
| GitHub OAuth | authlib 1.3.0 | 運作中 |
| Google OAuth | authlib 1.3.0 (OIDC) | 運作中 |
| Passkey/WebAuthn | (已規劃，尚未實作) | `.env.example` 已有變數 |

### 使用者模型 (PostgreSQL)

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

**關鍵缺口**: OAuth 使用者未儲存在資料庫中。Session cookie 是唯一的狀態。

### 工作階段管理

- `itsdangerous.URLSafeSerializer` (無過期時間)
- Cookie: `avator_session`, httponly, secure, samesite=lax
- 無 max_age (工作階段 cookie = 瀏覽器生命週期)
- OAuth 狀態儲存在獨立的 Starlette SessionMiddleware 中

### 工作階段載荷 (Session Payload)

```python
{"user": {"id": "github:12345", "email": "x @y.com", "method": "github"}}
```

### API 端點

| 方法 | 路徑 | 用途 |
|--------|------|---------|
| POST | /api/auth/register | 建立本地帳戶 (僅限 localhost) |
| POST | /api/auth/login | 密碼登入 |
| GET/POST | /api/auth/logout | 登出 (多種格式) |
| GET | /api/auth/check | nginx auth_request 探測 |
| POST | /api/auth/forgot | 密碼重設請求 (已停用: 501) |
| POST | /api/auth/reset | 使用權杖重設密碼 |
| GET | /auth/login/github | 啟動 GitHub OAuth |
| GET | /auth/callback/github | GitHub OAuth 回呼 |
| GET | /auth/login/google | 啟動 Google OAuth |
| GET | /auth/callback/google | Google OAuth 回呼 |

### OAuth 配置

- GitHub: `read:user user:email` 權限範圍，透過 `ALLOWED_GITHUB_USERS` 進行允許清單過濾
- Google: `openid email profile` 權限範圍，OIDC 發現機制，透過 `ALLOWED_GOOGLE_EMAILS` 進行允許清單過濾
- 兩者皆使用 authlib 的 `authorize_redirect` → `authorize_access_token` 流程

### 前端 (伺服器端渲染 HTML)

- 登入頁面：OAuth 按鈕 + 密碼表單
- 註冊頁面：僅限 localhost
- 應用程式頁面：受保護應用程式的網格視圖
- 非單頁面應用程式 (SPA) — 使用伺服器端渲染的 Jinja2 範本

### 已知限制

1. OAuth 使用者不在資料庫中 (無法進行使用者管理)
2. 無工作階段過期機制 (僅限瀏覽器生命週期)
3. 忘記密碼功能已停用 (已配置 SMTP 但回傳 501)
4. 儘管 .env.example 有相關變數，但未實作 WebAuthn
5. 缺乏 CSRF 防護
6. 缺乏速率限制 (Rate limiting)
7. 註冊功能受限於 localhost

---

## 2. 開發者工具

### 2.1 disk-report

**位置**: `~/.claude/data/disk-report/`
**技術棧**: Python FastAPI + Jinja2, 埠號 9527
**功能**: 硬碟掃描 (du/df/apfs)、AI 分析 (Gemini/Claude)、刪除/清理操作
**前端**: 完整儀表板 (5 個分頁：概覽、大檔案、舊檔案、快取、報告)
**儲存**: 純檔案系統 (報告格式為 markdown)
**啟動**: LaunchAgent (每日 03:30 產生報告)
**API**: 8 個端點 (摘要、掃描、報告、刪除、清理快取、清空垃圾桶)
**安全性**: 受保護路徑驗證 (封鎖系統目錄、.claude、.ssh)

### 2.2 cost-server (LLM 使用量)

**位置**: `~/.claude/data/cost-server/`
**技術棧**: Node.js (無依賴), Unix socket `~/.claude/cost-server.sock`
**功能**: 單次工作階段成本追蹤、每日變更紀錄、過期工作階段過濾
**儲存**: `state.json` (透過 rename 進行原子寫入)
**啟動**: LaunchAgent (自動重啟)
**API**: 3 個端點 (POST /update, GET /stats, GET /health)

### 2.3 tmux-webui

**位置**: `~/Claude/projects/tmux-webui/`
**技術棧**: Python (aiohttp 或 FastAPI), 單一檔案 server.py
**功能**: 列出工作階段/窗格/視窗、傳送按鍵、網頁端控制
**前端**: 瀏覽器控制介面

### 2.4 kas-memory

**位置**: `~/Claude/projects/kas-memory/`
**技術棧**: TypeScript MCP Server ( @modelcontextprotocol/sdk)
**功能**: 混合搜尋 (BM25 + 餘弦相似度 + RRF)、從工作階段自動擷取、標籤系統、嵌入向量 (Ollama/OpenAI)、知識提升、KAS 個人資料
**儲存**: Markdown 檔案 (memories/)、JSON (嵌入向量、標籤、個人資料)
**工具**: 9 個 MCP 工具 + 2 個資源
**鉤子**: extract.sh (工作階段結束), recall.sh (使用者提交提示詞)

### 2.5 session-redactor

**位置**: `~/Claude/projects/session-redactor/`
**技術棧**: Python FastAPI (V1 平台的子路由)
**功能**: 20 種正規表示式模式、支援 JSON 的遞迴去識別化、每日清理
**儲存**: SQLite (檔案追蹤、透過 inode 去重)
**API**: 4 個端點 (狀態、掃描、歷史紀錄、按工作階段查詢歷史)

### 2.6 觀測性 (observability)

**位置**: `~/Claude/projects/claude-code-hooks-multi-agent-observability/`
**技術棧**: Bun + SQLite (伺服器), Vue 3 + Vite + Tailwind (用戶端)
**埠號**: 4000 (伺服器) + 5173 (用戶端)
**功能**: 12 種鉤子事件類型、即時 WebSocket 儀表板、人機協作 (HITL)、代理人泳道、主題系統
**前端**: 完整的 Vue 3 儀表板，包含即時脈動圖、事件時間軸、過濾面板
**鉤子**: 12 個 Python 腳本 (工具使用前後、工作階段生命週期等)

---

## 3. V1 應用程式 (來自 auth /apps 頁面)

| 應用程式 | 路徑 | 描述 |
|-----|------|------------|
| Avatar Console | /console/ | 聊天介面 (Vue SPA) |
| Finance | /finance | 記帳應用程式 |
| Ideas | /ideas | 知識圖譜 |
| OpenClaw | /openclaw/ | (未知) |
| Terminal | /terminal/ | 網頁終端機 |
| Disk Report | /apps/disk-report/ | 硬碟分析 |
| Skill Galaxy | /apps/galaxy/ | 技能視覺化 |
| Daily Briefing | /apps/briefing/ | 每日情報摘要 |

---

## 4. V1 跨系統通用模式

### 運作良好之處 (保留)
- 使用 authlib 處理 OAuth (API 整潔，支援 OIDC 發現機制)
- 使用 itsdangerous 進行 cookie 簽章 (簡單且安全)
- 使用 LaunchAgent 處理背景服務 (macOS 原生機制)
- 以 Markdown 作為儲存格式 (kas-memory)
- 深色主題 (各工具間保持一致)

### 有待改進之處 (於 V2 修復)
- OAuth 使用者未存入資料庫 → V2：統一的使用者表 + oauth_accounts
- 無工作階段過期機制 → V2：由資料庫支援且具備 TTL 的工作階段
- 缺乏 WebAuthn → V2：使用 py_webauthn + @simplewebauthn/browser
- 缺乏 CSRF 防護 → V2：使用 double-submit cookie 或 SameSite strict
- 缺乏速率限制 → V2：使用 slowapi + Redis 後端
- 工具散亂 → V2：統一的專案結構
- 缺乏程式碼重用 → V2：共享函式庫 (Python + TypeScript)
- 缺乏觀測性 → V2：使用 OpenTelemetry + LGTM

### 遺漏之處 (於 V2 新增)
- 帳號連結 (相同 Email，多種提供商)
- 管理員使用者管理
- 多提供商驗證抽象化
- 中央事件匯流排 (Centralized event bus)
- 外掛系統
- 每個路由強制執行 RBAC+ABAC
