# Workshop 專案規則

## 身分與上下文
你是 Qwen Code，在 Workshop 專案中工作。這是一個 Modular Monolith + Event-Driven 架構。

## 技術棧
- **Backend**: Python 3.12 / FastAPI / uv (Modular Monolith, port 8801)
- **Frontend**: React 19 / TypeScript / Rsbuild / pnpm (Single App, port 3000)
- **Database**: PostgreSQL (per-module schema isolation)
- **Cache/Events**: Redis (cache + event bus)
- **Object Storage**: RustFS (MinIO fork, S3-compatible)
- **Realtime**: LiveKit (WebRTC), SSE (streaming)
- **Observability**: OpenTelemetry + LGTM (dev) / SigNoz (prod)

## 核心架構規則（鐵律）

### 模組邊界
- 模組 **禁止** import 其他模組的 `models.py` 或 DB tables
- 模組 **禁止** 寫入其他模組的 PostgreSQL schema
- 跨模組讀取 → 呼叫目標模組的 `services.py` (public API)
- 跨模組寫入 → 透過 EventBus 發布事件，禁止直接 DB 寫入
- 每個模組擁有一個 PostgreSQL schema：module name = schema name

### 13 核心模組
auth, finance, taskflow, ideagraph, admin, intelflow, memvault, skillpath, nodeflow, notification, invest, workpool, matchcore

### 事件驅動規則
- 命名：`{module}.{entity}.{past_tense}` (e.g., `finance.transaction.created`)
- 事件是不可變的
- Handlers 必須是冪等的
- Fire-and-forget — 如果需要回應，使用 service imports

## 程式碼慣例

### Backend 模組佈局 (`core/src/modules/<name>/`)
```
__init__.py    # Module registration, router export
routes.py      # FastAPI routes (HTTP layer only)
models.py      # SQLAlchemy models (module-scoped)
schemas.py     # Pydantic request/response schemas
services.py    # Business logic — THIS IS THE PUBLIC API
events.py      # Event subscribers
hooks.py       # Plugin hook points
deps.py        # FastAPI dependencies
```
其他模組只從 `services.py` import。禁止從 models.py 或 routes.py import。

### Frontend 模組佈局 (`workbench/src/modules/<name>/`)
```
components/    # Domain-specific components
pages/         # Route-level components
hooks/         # Domain-specific hooks
stores/        # Zustand stores (domain-scoped)
api/           # API client functions
types/         # Domain-specific types
index.tsx      # Module entry (export routes)
```

### 命名規則
- Backend modules: snake_case → `auth`, `finance`
- Frontend modules: 與 backend 一致
- Module name = DB schema = API prefix (`/api/<module>/`)
- Events: `{module}.{entity}.{past_tense}` — 永遠用過去式
- Errors: `{module}.{error_name}` — structured codes
- IDs: UUID v7 everywhere (uuid-utils)

### 共用程式碼閾值
程式碼放入 `shared/` 或 `libs/` **僅當** 被 2+ 模組使用。單一用戶使用 → 保持在本地。

## 安全規則

### 認證
- Signed cookies via itsdangerous (**非** JWT)
- Sessions 存在 Redis: `auth:session:{session_id}`
- Cookie flags: httponly=True, secure=True, samesite=lax
- Session expiry: 7 days default
- Password hashing: Argon2id preferred, bcrypt acceptable. **絕不**純文本。

### 授權：RBAC + ABAC
- Permission format: `{module}.{action}` (e.g., `finance.write`)
- 所有 routes.py **必須** 有 `require_permission()` — Nginx auth_request 是 Layer 1，FastAPI 是 Layer 2
- 唯一例外：`/status` health checks, public OAuth endpoints

### SQL Injection 防範
- f-string SQL with dynamic column/table names → **必須** whitelist validate
- User input in SQL intervals/identifiers → **必須** parameterize (`:placeholder`)
- `text(f"...")` is a red flag — add `# noqa: S608` only after whitelist validation

### SSRF Protection
- 任何接受 URLs 進行 server-side fetch 的 endpoint → **必須** 呼叫 `ssrf_guard.validate_url()`
- Blocked: 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, ::1

## Frontend 建構規則

Nginx 服務 `workbench/dist/` 作為靜態檔案（**非** proxy 到 dev server）。

### 任何 workbench 源碼變更後
```bash
cd /Users/joneshong/workshop/workbench && pnpm run build
```

### 驗證
```bash
grep -o 'src="[^"]*"' workbench/dist/index.html   # must show /static/...
head -1 workbench/dist/sw.js                        # must show workshop-<git-hash>
```

## 會話命名規則
收到會話的**第一則**用戶訊息時，使用內建 `/rename <title>` 命令重命名會話。
規則：verb-first, kebab-case, max 30 chars, 2-4 words.
範例：`fix-auth-middleware`, `add-paper-search`, `refactor-memvault-scoring`

## 多機器規則
- **Alembic migration 只在 Mac 主機跑**
- **Git branch 隔離** — 遠端工作在 `fleet/task-*` branch，不碰 main
- **Mac 不依賴 Windows** — Tailscale 斷線不影響 Mac 服務

## 蠶食（Cannibalization）原則
- 蠶食的是**設計模式**，不是核心引擎
- 蠶食 ≠ 複製貼上 — 根據生態系調整
- 獨立檔案 ≠ 整合 — 必須實際 import 和使用
- 5 層覆蓋：Backend → SDK → CLI → MCP → Skill

## 排程規則
- **Cronicle** (port 4105) 是唯一排程引擎
- **launchd** 僅做開機自起和離線自救（KeepAlive）
- 重度任務集中在 17:00-19:30（少爺外出晚餐時間）
- 避免深夜多個資源密集型任務同時執行

## 新增模組 Onboarding

### Core Module (port 8801)
1. App Launcher entry → `workbench/src/shared/constants/apps.ts`
2. Sentinel light check → `stations/sentinel/checker.py`
3. Sentinel deep check → `stations/sentinel/checker.py`
4. Frontend build → `pnpm run build`

### Standalone Station (own port)
以上全部 + 
5. Service registry → `scripts/workshop_services.py`
6. Sentinel remediation → `stations/sentinel/remediation.py`
7. Nginx reverse proxy → `/opt/homebrew/etc/nginx/conf.d/workshop-apps.inc`
