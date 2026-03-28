<!-- Synced from CLAUDE.md by sync-config -->
<!-- 手動修改可能在下次同步時被覆蓋 -->

---
doc_version: 5
content_hash: f6ad7751
source_hash: 4012b579
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# Workshop

Modular Monolith + Event-Driven workspace.

## Stack
- **Backend**: Python 3.12 / FastAPI / uv (Modular Monolith)
- **Frontend**: React 19 / TypeScript / Rsbuild / pnpm (Single App)
- **Database**: PostgreSQL (per-module schema isolation)
- **Cache/Events**: Redis (cache + event bus)
- **Object Storage**: RustFS (MinIO fork, S3-compatible)
- **Realtime**: LiveKit (WebRTC for voice/video), SSE (streaming)
- **Observability**: OpenTelemetry + LGTM (dev) / SigNoz (prod)

## Structure
- `core/` — Modular Monolith (13 Core Modules + hot-path services)
  - `core/src/modules/` — Domain modules (auth, finance, taskflow, ideagraph, intelflow, memvault, skillpath, workpool, matchcore, admin, nodeflow, notification, invest)
  - `core/services/realtime/` — LiveKit WebRTC gateway
  - `core/services/media/` — STT/TTS/image processing
- `workbench/` — Single React application
- `mcp/` — MCP server layer (17 servers: SDK-based protocol access to core services and stations)
- `stations/` — Standalone local tools (agent-metrics, agent-vista, anvil, envkit, hook-observatory, sandbox-executor, sentinel, session-archiver, session-intelligence, session-pipeline, session-redactor, system-monitor, tmux-relay, tmux-webui)
  - Each station's CLI lives in `stations/{name}/cli/`
- `core/cli/` — Core module CLI wrappers (finance, intelflow, auth, admin, notification, memvault, nodeflow)
- `vendor/` — Third-party community tools (observability)
- `bridges/` — External platform connectors (LINE, Telegram, Discord)
- `plugins/` — Plugin packages
- `libs/` — Shared libraries (python + typescript)
- `infra/` — Docker, Nginx, observability configs
- `scripts/` — Build/translate/deploy scripts
- `lab/` — POC experiments
- `docs/` — Architecture + Vision Documentation (Traditional Chinese, source of truth)
  - `docs/vision/` — Platform Vision (Manifesto, Domain Catalog, ADRs, Roadmap)
  - `docs/architecture/` — System Architecture, ADRs, Design Principles
- `docs-en/` — English backup (original English versions)

## Service Taxonomy
- **Foundation**: auth, admin, capture (shared schema, cross-module intake)
- **Domain Services** (DB-backed): finance, taskflow, ideagraph, intelflow, memvault, skillpath, workpool, matchcore, nodeflow, notification, invest
- **Bridges**: External connectors (social-hooks)
- **Hot-path Services**: media (STT/TTS/image), realtime (LiveKit)
- **Stations**: Standalone local tools (agent-metrics, agent-vista, envkit, hook-observatory, sandbox-executor, sentinel, session-archiver, session-intelligence, session-pipeline, session-redactor, system-monitor, tmux-relay, tmux-webui)
- **Vendor**: Third-party community tools (observability)
- **Compositions**: Service assemblies for specific use cases (Legal Advisor, Church Music, Virtual CS, ERP/POS)
- **SDK Clients**: `libs/sdk-client/sdk_client/` — unified Python SDK layer for all services (20+ clients)

## Core Concepts
- **LEGO Composition**: Services are reusable blocks. Projects = extend services + compose them. No "project vs module" distinction.
- **Event-Driven**: All state changes are events flowing through EventBus
- **RBAC+ABAC**: Role-based + attribute-based permission hybrid
- **Hook/Plugin**: Extensible via plugin manifest + hook bus
- **Module Boundaries**: Modules communicate via events (writes) or service imports (reads)
```
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3389ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3388ms



---

# Architecture

# Architecture Constraints

## Modular Monolith
- Single deployable unit: all 13 domain modules in one FastAPI process (port 8801)
- Two hot-path services run separately: realtime/LiveKit (8830), media/STT-TTS (8831)
- Frontend: single React app (workbench/, port 3000) — NO micro-frontend, NO Module Federation

## Module Boundaries (HARD RULES)
- Modules MUST NOT import another module's models.py or DB tables
- Modules MUST NOT write to another module's PostgreSQL schema
- Cross-module reads → call the target module's `services.py` (public API)
- Cross-module writes → publish events via EventBus, never direct DB writes
- Each module owns one PostgreSQL schema: module name = schema name

## 13 Core Modules

| Module | Domain | Phase |
|--------|--------|-------|
| auth | Authentication, sessions, spaces, permissions | 1 |
| finance | Transactions, budgets, subscriptions | 1 |
| taskflow | Quests, tasks, dispatch, rewards | 1 |
| ideagraph | Sparks, links, knowledge graph | 1 |
| admin | Platform management, audit logs | 1 |
| intelflow | RSS feeds, daily briefings | 2 |
| memvault | LLM memories, semantic search | 2 |
| skillpath | Skill trees, learning paths | 2 |
| nodeflow | Workflow orchestration, DAG execution | 2 |
| notification | Multi-channel notifications | 2 |
| invest | Investment tracking, portfolio analysis | 2 |
| workpool | Resources, scheduling, capacity | 3 |
| matchcore | Talent-job matching, scoring | 3 |

## Event-Driven Rules
- Naming: `{module}.{entity}.{past_tense}` (e.g., `finance.transaction.created`)
- Events are immutable — once published, data never changes
- Handlers MUST be idempotent — processing same event twice = no side effects
- Fire-and-forget — if you need a response, use service imports instead
- Keep payloads lean: IDs + essential data only; fetch full records via service imports

## Service Taxonomy
- **Foundation** (infra modules): auth, admin, capture (shared schema, cross-module)
- **Core Modules** (DB-backed): finance, taskflow, ideagraph, intelflow, memvault, skillpath, workpool, matchcore, nodeflow, notification, invest
- **Stations** (`stations/`): standalone local tools, no Core DB dependency
- **Bridges** (`bridges/`): external platform connectors (LINE, Telegram, Discord)
- **MCP servers** (`mcp/`): SDK-based protocol access to core services and stations (16 servers)
- **Vendor** (`vendor/`): third-party tools, used as-is, no modification

## Key Design Principles
- KISS: modular monolith > microservices (solo team)
- YAGNI: don't build for hypothetical future needs
- Prefer Existing: mature OSS > custom build (RustFS, LiveKit, react-grid-layout)
- MVP: each phase is a complete, usable product
- Composition > Inheritance: Service = BaseCRUD + EventBus + Permission


---

# Conventions

# Code Conventions

## Backend Module Layout (`core/src/modules/<name>/`)
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
Other modules import from `services.py` only. Never from models.py or routes.py.

## Frontend Module Layout (`workbench/src/modules/<name>/`)
```
components/    # Domain-specific components
pages/         # Route-level components
hooks/         # Domain-specific hooks
stores/        # Zustand stores (domain-scoped)
api/           # API client functions
types/         # Domain-specific types
index.tsx      # Module entry (export routes)
```
Frontend modules MUST NOT import from other modules. Cross-module via Router, custom events, or `src/shared/stores/`.

## Naming
- Backend modules: snake_case → `auth`, `finance`
- Frontend modules: match backend names
- Module name = DB schema = API prefix (`/api/<module>/`)
- Events: `{module}.{entity}.{past_tense}` — always past tense
- Errors: `{module}.{error_name}` — structured codes
- IDs: UUID v7 everywhere (uuid-utils)

## Shared Code Threshold
Code goes in `shared/` or `libs/` ONLY if used by 2+ modules. One user → keep it local.

## OOP Patterns
- `BaseCRUDService<M,C,U,R>` — Template Method with hooks: `before_create()`, `after_create()`, `to_response()`
- `SpaceScopedModel` — TimestampMixin + space_id + created_by (8/10 modules)
- `GlobalModel` — TimestampMixin only (auth, admin)
- `PaginatedResponse<T>` — all list endpoints return this format
- `WorkshopError` hierarchy — NotFoundError(404), ForbiddenError(403), ConflictError(409), BadRequestError(400)
- `createCrudApi<T,C,U>(basePath)` — frontend CRUD factory, one line per module
- `BridgeAdapter` ABC — polymorphic external platform connectors

## Configuration
- `pydantic-settings` with prefixed env vars (CORE_*, etc.)
- .env for local dev, env vars for production


---

# Frontend Build

# Frontend Build Rule

Nginx serves `workbench/dist/` as static files (NOT proxied to dev server).

## After ANY workbench source change

Rebuild:
```bash
cd /Users/joneshong/workshop/workbench && /opt/homebrew/Cellar/node@22/22.22.0/lib/node_modules/corepack/shims/pnpm run build
```

The build script automatically injects `git rev-parse --short HEAD` into `dist/sw.js` CACHE_NAME,
so every build produces a new SW version → browser detects byte-diff → installs new SW → purges old cache.

## Verify after build

```bash
grep -o 'src="[^"]*"' workbench/dist/index.html   # must show /static/...
head -1 workbench/dist/sw.js                        # must show workshop-<git-hash>
```

## Key facts

- V2 is at root `/` — no `BASE_PATH` needed (empty/unset)
- Nginx root `/` block has `Cache-Control: no-store` → sw.js always fetched fresh
- SW CACHE_NAME uses git hash (injected at build) — no manual version bump needed
- Incognito / browser cache clear does NOT clear SW CacheStorage — only SW version change clears it


---

# Module Onboarding

# New Module Onboarding Checklist

When adding a new frontend module or station, complete ALL applicable items before considering the task done.

## Core Module (runs inside core on port 8801)

Examples: briefing, finance, memvault, intelflow, notification

| # | Item | File |
|---|------|------|
| 1 | App Launcher entry | `workbench/src/shared/constants/apps.ts` |
| 2 | Sentinel light check (HTTP) | `stations/sentinel/checker.py` → `LIGHT_CHECKS` |
| 3 | Sentinel deep check (Playwright) | `stations/sentinel/checker.py` → `DEEP_CHECKS` + `_short_names` |
| 4 | Frontend build | `pnpm run build` in `workbench/` |

No separate service entry needed — core already managed by `scripts/workshop_services.py`.

## Standalone Station (own port, own process)

Examples: agent-metrics, hook-observatory, auto-survey, system-monitor

All of the above, plus:

| # | Item | File |
|---|------|------|
| 5 | Service registry | `scripts/workshop_services.py` → `SERVICES` |
| 6 | Sentinel remediation map | `stations/sentinel/remediation.py` → `SIMPLE_RESTART_MAP` |
| 7 | Nginx reverse proxy | `/opt/homebrew/etc/nginx/conf.d/workshop-apps.inc` |

## Reference: Existing Patterns

- **App Launcher entry**: Copy structure from `apps.ts`, set `status: 'available'` for internal routes, `status: 'external'` + `externalUrl` for station UIs
- **Sentinel light check**: Core modules use `group="internal"`, `expect_contains='<div id="root">'`; stations use `group="external"`
- **Sentinel deep check**: Core modules use `_PW_ROOT_CHECK`; stations use `_PW_BODY_CHECK`
- **Nginx proxy**: Include `auth_request /_v2_auth_check` + `error_page 401 = @auth_redirect` for authenticated access


---

# Security Hardening

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


---

# Security

# Security Rules

## Authentication
- Signed cookies via itsdangerous (NOT JWT)
- Sessions stored in Redis: `auth:session:{session_id}`
- Cookie flags: httponly=True, secure=True, samesite=lax
- Session expiry: 7 days default
- Password hashing: Argon2id preferred, bcrypt acceptable. NEVER plaintext.

## Authorization: RBAC + ABAC
- RBAC layer: role → permission set
  - admin: `*` (all), user: `{module}.read` + `{module}.write`, guest: `{module}.read` only
- Permission format: `{module}.{action}` (e.g., `finance.write`)
- ABAC layer on top: owner-only, status-check, rate-limit, time-window
- Apply: `@require_permission("finance.read")` + `enforce_policy("owner-only", ...)`

## User Lifecycle
- States: pending → active → suspended / banned
- Only `active` users can login and call APIs
- Suspend/ban immediately clears all sessions

## Plugin Permission Sandbox
- effective_permissions = plugin.declared ∩ current_user.permissions
- Plugins CANNOT access undeclared modules
- Plugins CANNOT escalate beyond the invoking user

## Network
- All services bind to 127.0.0.1 — external traffic only through Nginx
- CSRF: SameSite cookies + optional CSRF token for mutations
- All inter-service calls (Core → Media, Core → Realtime) are localhost HTTP


---

# Audit Soft Delete

# Audit Trail + Soft Delete (2026-03-03)

## 架構概要
- **SoftDeleteMixin** (`deleted_at` column) 加入 `SpaceScopedModel`，所有 domain model 自動繼承
- **AuditLog** 表在 `admin` schema，集中管理跨模組 audit records
- **BaseCRUDService** 內建 `_record_audit()`，同 DB transaction 保證一致性
- Diff 格式：`{field: {old, new}}` JSONB — create/delete 記 snapshot，update 記 changes

## 關鍵方法（BaseCRUDService）
| 方法 | 用途 |
|------|------|
| `_snapshot(instance)` | ORM → dict（處理 Decimal/datetime/date） |
| `_compute_diff(old, new)` | field-level diff（只比對 old_snapshot 的 keys） |
| `_record_audit(db, action, ...)` | 寫入 admin.audit_logs |
| `get_including_deleted()` | 含已刪除 |
| `list_deleted()` | 垃圾桶列表 |
| `restore()` | 還原 soft-deleted |
| `purge()` | 永久硬刪除 |

## 啟用方式
```python
class MyService(BaseCRUDService[...]):
    audit_module = "finance"       # 空 = 不審計
    audit_entity_type = "transactions"  # 空 = 用 __tablename__
```

## Finance 特殊處理
- `delete()` → soft delete + balance reversal（wallet.current_balance 扣回）
- `restore()` → re-apply balance delta
- Trash endpoints: `GET/POST/DELETE /api/finance/trash/{entity_type}/{id}`
- `svc_map` dict 路由 entity_type → service instance

## Migration
- `m4e5f6g7h8i9`：merge 2 heads → admin schema + audit_logs + 23 表 deleted_at
- 跳過 `finance.wallets`（已有自己的 deleted_at）

## Unit Test 修復（72/72 pass）
加入 soft delete 後需同步更新 mock-based unit tests：
1. **MagicMock 的 `deleted_at` 陷阱**：`MagicMock(spec=Model)` 會自動產生 `deleted_at` 屬性（truthy），`BaseCRUDService.get()` 的 soft-delete 過濾會誤判為已刪除 → fixture 必須顯式 `t.deleted_at = None`
2. **Schema field 重命名需同步測試**：`CategoryBreakdown` 的 `total→amount`、`percentage→pct` 改名後測試未更新 → `AttributeError`
3. **新增 DB query 需擴充 mock side_effect**：`monthly_summary()` 新增 wallet overview 查詢（第 3 次 `db.execute`），原本 `side_effect=[totals, cats]` 只有 2 項 → `StopAsyncIteration`。修復：加 `wallet_result` mock
4. **MagicMock 不能通過 Pydantic str 驗證**：`cat_row.category_icon` 未設定 → MagicMock 物件傳入 `CategoryBreakdown(category_icon=...)` 觸發 `ValidationError`。修復：顯式 `category_icon=None`

## 踩過的坑
1. **`date` vs `datetime` 序列化**：`_serialize_value()` 只處理 `datetime`，`date`（subscription.start_date）不是 datetime 子類 → 500。修復：`isinstance(value, (datetime, date))`
2. **Alembic merge downgrade**：`alembic downgrade -1` 在 merge migration 會 "Ambiguous walk" → 需指定具體 revision：`alembic downgrade l3d4e5f6g7h8`
3. **Worktree 的 `uv run` 問題**：workspace member `services/core` 路徑在 worktree 不存在 → 用 `.venv/bin/alembic` 直接執行
4. **`_compute_diff` 只遍歷 old keys**：設計決定 — snapshot 來自同一 ORM model 所以 keys 一致，不需處理新增/刪除欄位
5. **Linter 自動移除 unused import**：auto-format hook 會在 Edit 後自動 ruff --fix，如果 import 還沒被使用就會被移除 → 需在同一次 Edit 中同時加 import 和使用


---

# Cannibalize Lessons

# 蠶食（Cannibalization）執行經驗

首次完整蠶食案例：Crawl4AI → Workshop（2026-03-09）

## 7 條執行鐵律

### 1. 分清「引擎」與「設計模式」
蠶食的是設計模式（rate limiting、chunking、enrichment pipeline），不是核心引擎。
crawl4ai 的瀏覽器自動化 + JS 渲染 = 引擎，繼續用它；設計模式 = 自己寫，零依賴。
**判斷標準**：如果我們自己重寫需要 >2 週且社區已有成熟實作 → 用引擎不蠶食。

### 2. 蠶食 ≠ 複製貼上
最關鍵的教訓。少爺明確糾正過：蠶食是根據我們生態系調整，或修改生態系去配合好設計。
- RateLimiter：不照抄 crawl4ai 的 dispatcher，而是取「per-domain lock + exponential backoff」模式，配合我們的 asyncio 架構
- EnrichmentPipeline：不照搬 ExtractionStrategy，而是取「composable strategy chain」模式，接入 capture promote() 流程
- 每個萃取出來的模組都要能獨立被其他 Workshop 模組使用，不限於 crawl 場景

### 3. 獨立檔案 ≠ 整合
創建 `core/src/shared/rate_limiter.py` 只是第一步。真正的蠶食必須接線：
- rate_limiter.py 要接入 `intelflow/webcrawl.py` 的 acquire/report 流程
- chunking.py 要接入 `shared/embedding.py` 的 get_embeddings_chunked()
- strategies.py 要接入 `capture/services.py` 的 promote() 路徑
**鐵律**：沒有被 import 的模組就是死碼。E2E 測試必須驗證接線，不只驗證獨立功能。

### 4. 隔離重依賴 — subprocess JSON 橋接
crawl4ai 帶 numpy、lxml、playwright 等重依賴 → 安裝在 `~/.venvs/crawl4ai/` 隔離 venv。
Workshop 透過 `crawl4ai_bridge.py` 用 subprocess + stdin/stdout JSON 通訊。
**好處**：主 venv 完全不受污染；升級 crawl4ai 只需 pip install -U，不影響 Workshop。

### 5. vendor/ 是參考不是依賴
`vendor/crawl4ai/` 存放完整原始碼，但 **永不 import**。它的價值是：
- 方便 grep/read 學習模式
- 追蹤上游變化（可定期 git pull 比對）
- 記錄我們蠶食了哪些部分
**注意**：vendor/ 的 pyproject.toml 會干擾根目錄的 `uv run`，必須從 `core/` 目錄執行。

### 6. 蠶食的 5 層覆蓋必須完整
Backend → SDK → CLI → MCP → Skill，缺一層就不算完成。
Crawl4AI 蠶食的 5 層：
- Backend: rate_limiter, chunking, url_filter, url_scorer, markdown_gen, adaptive, enrichment strategies
- SDK: `libs/sdk-client/sdk_client/crawl4ai.py`
- CLI: `core/cli/crawl4ai_cli.py` (crawl/chunk/filter/score/html2md)
- MCP: `mcp/crawl4ai/server.py` (8 tools)
- Skill: `~/.gemini/skills/webcrawl/SKILL.md`

### 7. 測試策略：單元 + E2E 接線雙層
- **單元測試** (40)：每個獨立模組的 API 正確性
- **E2E 接線測試** (20)：驗證模組間的 import、呼叫、資料流是真實的
  - 用 `inspect.getsource()` 驗證原始碼確實包含整合程式碼
  - 用 mock 隔離外部 I/O（網路、DB），但不 mock 內部接線
  - 驗證 patch 路徑正確：lazy import 的函數要 patch 來源模組，不是使用模組

## 蠶食適用性判斷清單

| 條件 | 適合蠶食 | 不適合 |
|------|---------|--------|
| 設計模式可複用 | ✅ | 高度定制化的業務邏輯 |
| 我們有對應模組承接 | ✅ | 需要新建整個子系統 |
| 源碼品質可信 | ✅ | Star 注水 / 品質堪憂 |
| 工作量 ≤ 2-3 天 | ✅ | 需要 >1 週重寫核心 |
| 社區活躍（可借力） | ✅✅ | 已棄坑 / 個人 side project |
| 重依賴可隔離 | ✅ | 必須整合進主 venv |

## Commit 記錄

### Crawl4AI（2026-03-09）
1. `abc2324` — Phase 1：adaptive runner, manifest, enrichment strategies
2. `7d87698` — Phase 2+3：bridge, webcrawl service, capture adapter
3. `64d37e6` — Batch 1：5 shared utilities + 5-layer coverage
4. `5bd2522` — Deep integration：5 real wiring points + 20 E2E tests

### ACPX（2026-03-09）
5. `f0ddbb7` — 5 design patterns：Correlation ID, Queue Owner, Turn Controller, ensure(), exit codes

## ACPX 蠶食補充經驗

### 8. 概念蠶食 vs 代碼蠶食
ACPX 與 Crawl4AI 不同：是「概念蠶食」而非「代碼蠶食」。
源碼不存在可直接參考的實作，只有設計模式描述 → 自己從零實作。
**鐵律**：概念蠶食的驗收標準更高 — 沒有原始碼可對照，必須靠充足的測試覆蓋來確保正確性。

### 9. 循環 import 是蠶食的常見坑
加入 ContextVar 到 bus.py 時造成循環 import（bus.py ↔ memory.py）。
**解法**：把共用的 ContextVar 搬到 base.py（不依賴任何子模組的抽象層）。
**鐵律**：修改事件系統等核心基礎設施時，必須先跑一次 import 測試。

### 10. 子 agent 的 import 路徑必須審查
Agent 產出的測試使用 `from core.src.shared...` 而非 `from src.shared...`。
**原因**：agent 不知道 pytest 的 sys.path 設定（conftest.py 加了 core/ 到 path）。
**鐵律**：並行 agent 產出的測試必須跑一輪才 commit，不可盲信。


---

# Feedback Cannibalize Bloat

---
name: feedback_cannibalize_humility
description: 蠶食整合的心態問題 — 要謙卑學習而非居高臨下評判
type: feedback
---

蠶食整合時要保持謙卑的學習心態，不要高高在上睥睨一切。

**Why:** 最近的蠶食流程變成一種「我來評判你值不值得被我吸收」的姿態 — 打分數、列缺點、挑毛病。這個心態本身就是膨脹。每個開源專案的作者都花了心血，每個設計選擇背後都有我們可能沒看到的脈絡。我們自己的生態系也有大量不足之處。

**How to apply:**
- 蠶食的出發點是「我能從這裡學到什麼」，不是「這個專案夠不夠格被我蠶食」
- 積極尋找值得學習的地方，而非列出不足之處來證明自己更好
- 反思我們自身的差距 — 別人做到了什麼我們還沒做到的？
- 凡事都有可以學習的地方，永無止境
- 評分和判定框架可以保留，但態度要從「審判者」轉為「學習者」


---

# Feedback Ex Quota Negative

---
name: EX 負值餘額不該顯示
description: tmux-webui 狀態列中 Claude EX 餘額為負或零時，必須完全隱藏，不可顯示
type: feedback
---

Claude EX (Extra Credits) 餘額小於等於零時，必須從 tmux-webui 狀態列中完全隱藏。

**Why:** 少爺已反覆提及五次以上。EX 餘額耗盡後持續顯示負值毫無意義且造成視覺干擾。tmux_status.py 的 powerline 已正確過濾（`<= 0 → return ""`），但 tmux-webui 的 API→前端路徑完全沒有相同的防護。

**How to apply:** 任何涉及 quota 顯示的修改，都必須在以下三層加防護：
1. `quota_collector.py` — 資料源層：balance <= 0 時 ex 值標記為隱藏
2. `routes/sysmon.py` — API 層：過濾負值 ex
3. `metrics.js` — 前端層：檢查負值或 "off"，不渲染


---

# Feedback No Rerun Old

---
name: feedback_no_rerun_old
description: 不要重跑過去的測驗或修復歷史資料，過去的就讓它過去
type: feedback
---

不要重跑過去的測驗或補救歷史資料，只修好程式碼即可。
**Why:** 少爺認為過去的事不需要追溯修復，重跑已完成的測驗沒有意義。
**How to apply:** 發現歷史資料有問題時，只修程式碼防止未來再發生，不要主動刪除舊 submissions 去重跑。


---

# Feedback Scheduling Roles

---
name: scheduling-engine-roles
description: Cronicle 是唯一排程引擎，launchd 僅做開機自起和離線自救，禁止混淆兩者角色
type: feedback
---

Cronicle（port 4105）是 Workshop 唯一的定時排程引擎，所有 periodic jobs 由 Cronicle 排程執行。
launchd 的角色僅限於：開機自起（RunAtLoad）+ 離線自救（KeepAlive）— 即 daemon 進程管理。

**Why:** 少爺在 2026-03-13 修正：我錯誤地將 manifest.json 的 schedule 格式（calendar/interval）解讀為 launchd StartCalendarInterval，並錯誤宣稱「launchd 取代了 Cronicle」。實際上 manifest.json 的 periodic jobs 全部透過 seed_jobs.py 同步到 Cronicle REST API 執行。

**How to apply:**
- 談到排程系統時，永遠說「Cronicle 是主力排程引擎」
- launchd 只在 daemon keepalive 語境下提及
- manifest.json 的 periodic jobs → Cronicle 執行；daemon type → launchd KeepAlive
- 禁止說「launchd 執行排程」或「launchd 取代 Cronicle」


---

# Llm Provider Dashboards

---
name: LLM Provider Usage Dashboards
description: 各 LLM 供應商儲值餘額查詢 Dashboard URL（minimax, moonshot, zhipu, deepseek, dashscope, xai）
type: reference
---

各供應商的用量/餘額查詢 Dashboard（key = provider name，非 model name）：

| 供應商 (key) | 公司 | 模型家族 | Dashboard URL | 儲值 |
|---|---|---|---|---|
| minimax | MiniMax（稀宇） | MiniMax-Text, abab | https://platform.minimax.io/user-center/payment/balance | $25 |
| moonshot | Moonshot AI（月之暗面） | Kimi, moonshot-v1 | https://platform.moonshot.ai/console/account | $25 |
| zhipu | Z.AI（智譜） | GLM-4, GLM-5 | https://z.ai/manage-apikey/billing | $10 |
| deepseek | DeepSeek（深度求索） | DeepSeek-V3, R1 | https://platform.deepseek.com/usage | $12 |
| dashscope | DashScope（阿里/通義） | Qwen, Qwen3 | https://modelstudio.console.alibabacloud.com/ap-southeast-1/?tab=dashboard#/model-usage/free-quota | 免費額度 |
| xai | xAI | Grok | https://console.x.ai/team/f0ca6117-e73f-4fec-b5ab-4391eb612200/billing | $25 |

**How to apply:** `ws_provider_balance_sync.py` 每日 17:45 自動爬取同步到 Redis。全部使用 Google OAuth 登入。


---

# Memvault Lessons

# Memvault 開發經驗（2026-02-24 ~ 2026-02-27）

## Bug Patterns

### 1. Pipeline 無聲失敗（Silent Fallback）
- **問題**：extract pipeline 的 blocks/triples 因 API schema 不匹配，寫入 DB 失敗後無聲 fallback 到本地 JSONL
- **影響**：KG 長期空白，但表面看起來 pipeline 正常運作
- **教訓**：Pipeline fallback 邏輯必須有明確的 warning log + metrics；寧可 fail loud 也不要 fail silent
- **防範**：在 pipeline 中加入 assertion — 若 API 回傳非 2xx，raise 而非 fallback

### 2. 多層 Pipeline 連鎖故障
- **問題**：extract → cluster → wisdom 三層 pipeline，L0 失敗 → L1 拿不到 triples → L2 拿不到 clusters → 全鏈空
- **教訓**：Pipeline 各層應有獨立的健康檢查（「L0 有 N 筆 triples 嗎？」），不是只檢查最終輸出
- **防範**：Pipeline 起始前先 GET 上游資料量，若為 0 則 early exit + 告警

### 3. API 分頁錯誤
- **問題**：Cluster pipeline 呼叫 triples API 時分頁邏輯有誤，只拿到第一頁
- **教訓**：呼叫分頁 API 時務必 loop 到 total，或用無分頁的 batch endpoint

## Architecture Decisions

### 4. 類型映射在 API Boundary
- **決策**：Pipeline 產出的細粒度 block type（insight, technical, achievement）在 API 入口層映射到 KAS canonical types（knowledge, skill, attitude, general）
- **錯誤做法**：擴展 DB enum 來接納所有 pipeline type → 破壞 KAS 框架語意
- **正確做法**：`BLOCK_TYPE_ALIASES` dict 在 `schemas.py` + `before_create()` hook 映射

### 5. kg_ Prefix 檔案擴展模式
- **決策**：KG 功能作為 memvault 模組的「擴展」，用 `kg_models.py`、`kg_services.py`、`kg_routes.py` 而非塞進既有檔案
- **優點**：核心檔案不膨脹、可獨立 review、import 路徑清晰
- **適用**：當模組功能明確分為「核心 + 擴展」兩層時

### 6. Predicate Normalization
- **問題**：LLM 提煉 triples 時同義述詞爆炸（has_learned / know / learned / understands）
- **解法**：`kg_config.py` 中 40+ alias → 20 canonical predicates 的映射表
- **教訓**：任何 LLM 生成的結構化欄位都需要 normalization layer

## Trade-offs

### 7. Mem0 Versioned Attitudes
- **設計**：self-referential FK（superseded_by + previous_version）形成版本鏈
- **代價**：查「當前有效」需 `WHERE superseded_by IS NULL`（partial index 緩解）；查歷史需遞迴 JOIN
- **值得**：捕捉信念演化軌跡是 KAS 的核心價值

### 8. Cascade Recall 跨層分數正規化
- **問題**：L0 triple 的 cosine similarity、L1 cluster 的 summary similarity、L2 wisdom 的 similarity 尺度不同
- **暫解**：各層獨立排序後合併，不做跨層 score normalization
- **待改善**：可能需要 reciprocal rank fusion 或 learned weights

### 9. Tag Denormalization
- **設計**：獨立 `Tag` 表存聚合計數，需 `sync_tags()` 重建
- **代價**：write amplification（每次 block CRUD 後需 sync）
- **收益**：instant tag autocomplete + histogram queries

## Search Quality — 7 Defense Architecture (2026-03-03)

### 11. 七道搜尋防線（from memory-lancedb-pro）
- **Pipeline**: Query → ④Adaptive Retrieval → ⑤Task-Aware Embed → Vector∥Keyword → ③RRF → ①Noise Filter → ②Scoring Pipeline → ⑥Reranker → ⑦Scope Filter
- **關鍵檔案**: `noise_filter.py`, `scoring_pipeline.py`, `reranker.py`, `scopes.py`（均在 `core/src/modules/memvault/`）
- **shared/embedding.py**: 新增 `task_type` 參數，支援 `search_query:` / `search_document:` prefix
- **69 tests** 全部通過（`core/tests/test_memvault.py`）

### 12. Task-Aware Embedding Re-processing
- nomic-embed-text 支援 prefix：`search_document:` (索引) vs `search_query:` (查詢)
- 舊 370 blocks 無 prefix → re-embed 後 top-1 平均 +3.8%（5/5 queries improved）
- 腳本：`core/scripts/memvault_re_embed.py`，370 blocks / 12.9s / 0 failed
- 備份表：`memvault.blocks_embedding_backup` + `memvault.block_embeddings_backup`

### 13. Deduplication — 41% 重複率
- 370 blocks 中 152 筆重複（218 unique），worst case 同內容 17 copies
- 策略：soft delete（`deleted_at = NOW()`），保留最舊的那筆
- 同時清理 `block_embeddings` 子表中 orphaned 記錄
- **教訓**：MCP memvault_extract 對同一 session 重複呼叫會產生大量重複 → 需在 extract 層加 content dedup

## Config & Patterns

### 10. Embedding Graceful Degradation
- **模式**：`get_embedding()` 返回 `None` 表示 Ollama 不可用 → routes 自動 fallback 到 ILIKE text search
- **關鍵**：不要讓 embedding 失敗阻擋 CRUD 操作
- **HNSW 參數**：m=16, ef_construction=64 對 ~1500 triples 的資料量合適；大規模需重新 tune


---

# Pwa Multi Module

# PWA 多模組獨立安裝（2026-03-06 完整攻略）

## 架構概覽

同一個 SPA（workbench）下 10 個模組各自獨立安裝為 PWA：
- 每個模組有獨立 manifest、icon、HTML entry、Nginx location
- Root PWA（Workshop Launcher）scope 限定在 `/apps/`，不與模組重疊

## 三大根因（按嚴重程度排序）

### 1. Manifest scope 重疊（最致命）
- Root manifest `scope: "/"` 吞掉所有模組 → 瀏覽器視為同一 app
- **修正**：root `scope: "/apps/"`，各模組 `scope: "/{module}/"`，完全不重疊
- iOS Safari 不支援 `id` 屬性，完全依賴 `scope` 判斷 PWA 身份
- Chrome 96+ 用 `id` 判斷，但重疊 scope 仍抑制安裝提示
- 參考：https://web.dev/articles/building-multiple-pwas-on-the-same-domain

### 2. SPA 客戶端導航不重載 HTML
- React Router `navigate()` 不觸發頁面重載 → 手機 manifest 鎖定在初始頁面
- **修正**：AppLauncher 模組切換改 `window.location.href`（全頁載入）
- `useManifest` hook 動態切換：Chrome 桌面/Android 有效，iOS 無效（雙保險）

### 3. 舊 Service Worker 快取
- SW 用 git hash 做 CACHE_NAME，沒 commit 就不會更新
- 手機上舊 SW 快取了舊 HTML/manifest → 即使伺服器正確也讀到舊的
- **修正**：提供 `/pwa-debug.html` 診斷頁，含 Clear Cache + Unregister SW 按鈕
- **教訓**：PWA 變更後，手機必須清 SW 快取才能生效

## 完整設定清單（10 個模組）

### Per-module 檔案
| 檔案 | 位置 | 用途 |
|------|------|------|
| `manifest-{module}.json` | `workbench/public/` | PWA manifest（id, scope, start_url, icons） |
| `icon-{module}-192.{svg,png}` | `workbench/public/icons/` | 192px icon |
| `icon-{module}-512.{svg,png}` | `workbench/public/icons/` | 512px icon |
| `{module}.html` | `workbench/dist/`（build 產出） | Module-specific HTML entry |

### 集中配置
| 檔案 | 用途 |
|------|------|
| `gen-module-html.sh` | Build 後置腳本，從 index.html 產生模組 HTML（sed 替換 manifest/icon/title/theme-color） |
| `useManifest.ts` | React hook，動態同步 manifest/icon/theme-color（Chrome 補強） |
| `AppLauncher.tsx` | 模組切換用 `window.location.href`（非 SPA navigate） |
| `workshop.joneshong.com.conf` | Nginx per-module location block |

### Nginx location block 模式
```nginx
location = /{module} { return 301 /{module}/; }
location /{module}/ {
    alias /Users/joneshong/workshop/workbench/dist/;
    try_files $uri /{module}.html;
    add_header Cache-Control "no-store" always;
}
```

### Manifest 模式
```json
{
  "id": "/{module}",
  "name": "模組中文名",
  "short_name": "EnglishName",
  "start_url": "/{module}/",
  "scope": "/{module}/",
  "display": "standalone",
  "background_color": "#1e1e2e",
  "theme_color": "#模組色",
  "icons": [
    {"src": "/icons/icon-{module}-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/icons/icon-{module}-512.png", "sizes": "512x512", "type": "image/png"}
  ]
}
```

### gen-module-html.sh gen() 呼叫
```sh
gen {module} "中文名" "#theme_color" 1
# 第 4 參數 "1" = 替換 icon 路徑（有專屬 icon）
```

## 新增模組 PWA 步驟

1. 建立 `public/manifest-{module}.json`（參考上方模式）
2. 生成 icon：`public/icons/icon-{module}-{192,512}.{svg,png}`
3. `gen-module-html.sh` 加一行 `gen {module} "名稱" "#color" 1`
4. `useManifest.ts` MODULE_PWA 加一筆
5. Nginx 加 location block
6. `pnpm run build`

## Icon 生成

SVG 模式：圓角深色方塊 + 粗體字母（模組 theme_color）
PNG：用 Pillow 或 sandbox 批次生成
字母對照：F(finance) T(taskflow) I(ideagraph) A(admin) N(nodeflow) $(invest) !(notification) B(briefing) M(memvault)

## 診斷工具

`/pwa-debug.html`：手機瀏覽器開啟，顯示：
- 當前 DOM manifest 連結 + 內容
- SW 狀態（scope, version, waiting/installing）
- Cache Storage 內容
- Display mode（standalone = 已安裝 PWA，manifest 鎖定）
- 4 按鈕：Force SW Update / Clear Caches / Unregister SW / Re-run

## 鐵律

- **Scope 絕不重疊**：root `/apps/`，模組 `/{module}/`
- **手機安裝前必清 SW**：舊快取會覆蓋伺服器回應
- **模組切換用 full reload**：`window.location.href` 不用 React Router navigate
- **已安裝 PWA 的 manifest 不會自動更新**：需刪除重裝
- **iOS Safari 不支援 manifest `id`**：只靠 scope 識別


---

# Qwen Free Quota

---
name: Qwen Free Quota
description: Alibaba DashScope Qwen 免費額度監控 — 95 模型各 1,000,000 tokens，幾乎未使用
type: reference
---

Qwen (Alibaba DashScope) 免費額度資訊

**Dashboard URL**: https://modelstudio.console.alibabacloud.com/ap-southeast-1/?tab=dashboard#/model-usage/free-quota

**額度概況**（2026-03-13）：
- 95 個模型，每個 1,000,000 免費額度
- 90 個額度充沛，0 個超過 50%，0 個超過 80%
- 5 個無免費額度的模型

**TOP 3 使用量**（幾乎未用）：
- qwen3-max: 剩 999,961 / 共 1,000,000 (0%)
- qwen-max: 剩 999,984 / 共 1,000,000 (0%)
- qwen3.5-122b-a10b: 剩 1,000,000 / 共 1,000,000 (0%)

**監控方式**：可定期用 Playwright CLI 或 osascript+Safari 自動抓取免費額度頁面

**How to apply:** LiteLLM MANUAL_QUOTAS 中 qwen total=0 是因為無儲值（純免費額度），實際可用量極大。當討論 Qwen 成本時提醒免費額度充足。


---

# Resilience Patterns

# Resilience Patterns — 踩坑記錄

## 1. Middleware 必須容錯所有輸入（含舊版資料格式）

**事件 A**：2026-03-03 auth login 500（Redis 失敗）
**根因**：`session.py` middleware 的 Redis lookup 沒有 `except`
**修復**：加 `except Exception` → 降級為未認證狀態

**事件 B**：2026-03-03 auth login 500（舊版 cookie 格式）
**根因**：舊版 middleware 把完整 session dict 塞進 cookie，新版只存 token str。`_serializer.loads()` 還原出 dict，`.encode()` 炸 `AttributeError`，且此 exception 在 try/except **外面**
**修復**：`isinstance(payload, str)` 型別守衛，非 str 一律視為無效

**規則**：
- Middleware 裡的外部呼叫（Redis、DB、HTTP）**必須** try/except，失敗時降級而非爆炸
- **反序列化後必須驗型別** — 格式遷移期間新舊 payload 共存，不能假設型別
- Middleware 是全域的 — 一個 middleware 崩 = 整個 API 崩
- Route handler 裡的外部呼叫可以 500（影響範圍限於單一請求）

**檢查清單（寫新 middleware 時）**：
1. Redis/DB 呼叫有 except？
2. 反序列化結果有 isinstance 守衛？
3. 失敗時 request.state 是否仍被正確初始化？
4. finally 裡有 close/cleanup？

## 2. Embedding 服務必須有 retry + 限流

**事件**：2026-03-03 intelflow 429
**根因**：`embedding.py` 對 Ollama 無 retry/backoff 也無並發限制，backfill 時 600+ 呼叫壓垮 Ollama
**修復**：
- `asyncio.Semaphore(4)` 限制並發
- 指數退避重試（1s/2s/4s）on 429/503/502/timeout
- 可重試判定：`_is_retryable()` 函數

**規則**：
- 所有對外部服務的 HTTP 呼叫都要考慮 retry + backoff
- 批次操作必須限流（semaphore 或 rate limiter）
- Ollama 是單機服務，並發能力有限 — max 4 concurrent

## 3. 服務重啟注意事項

- **永遠不要手動 kill + python3 重啟** launchd 管理的 station — 缺環境變數 + 佔 port
- 正確做法：`workshop-services.sh restart <name>` 或 `launchctl kickstart -k`
- crash-loop 時檢查：port 是否被占、.env 是否可讀、secret key 是否設定
- launcher daemon 會自動拉起服務，但 PID 檔可能不同步 — 用 `lsof -i :<port>` 確認

## 4. 除錯 500 必須用真實 cookie 重現

**事件**：2026-03-03 反覆 curl 測試看不到 500，浪費三輪排查
**根因**：curl 不帶 cookie → middleware 跳過 cookie 解析 → 不觸發舊格式爆炸路徑。真實用戶的 iPhone 持有舊版 cookie → 每次都炸
**教訓**：
- **500 排查第一步是讀 error log**，不是盲目 curl — log 裡有完整 traceback 和 exception 類型
- curl 測 auth 相關端點時**必須帶 cookie**（`-b "workshop_session=..."`)，否則跳過整段認證邏輯
- 格式遷移後，主動用舊格式 payload 產生 cookie 做回歸測試
- 用戶說 500 但 curl 重現不了 → 立刻懷疑「用戶帶了什麼 curl 沒帶的東西」（cookie、header、舊快取）

## 5. Route handler 的 db.commit() 一致性

**事件**：2026-03-03 login handler 缺 `db.commit()`
**根因**：`register` 和 OAuth callbacks 都有 `await db.commit()`，`login` 獨缺。`_create_session()` 內部只做 `flush()`，session 記錄在 request 結束時 rollback → Redis 有 token 但 DB 無記錄
**教訓**：
- 同一組 CRUD 路由裡 commit 模式必須一致 — 一個有 commit 其餘都要有
- `flush()` ≠ `commit()` — flush 只寫到 DB buffer，transaction 結束可能 rollback
- 寫新 route 時對照同模組其他 route 的 commit 模式

## 6. Nginx rate limit 對 SPA/PWA 的影響

**事件**：2026-03-03 station 頁面載入被限流 → 靜態檔 503
**根因**：全域 `limit_req zone=global burst=20`，一個 SPA 頁面載入觸發 10-20 個並行請求（HTML+CSS+JS+fonts+manifest+SW），瞬間超限
**修復**：V2 station locations 加 `burst=100 nodelay`
**教訓**：
- SPA/PWA 頁面載入的並行請求數遠超傳統 server-rendered 頁面
- 對 reverse proxy 的 station，rate limit 要在 location block 層級覆寫，不能只靠 server 層預設
- 503 被用戶回報為「500」— 排查時要查 Nginx error log 的 `limiting requests` 條目

## 7. Station 登入連結不可用 localhost

**事件**：2026-03-03 hook-observatory AuthGuard `href="http://localhost:8800/v2/login"`
**根因**：開發時用 localhost 測試，上線忘改。PWA 從外網存取時 localhost 不可達
**修復**：改為相對路徑 `/v2/login`
**教訓**：
- Station 前端的任何 URL **一律用相對路徑**（`/v2/login`），永遠不硬編碼 host:port
- code review 時 grep `localhost` — 除了後端 config 之外不應出現在前端程式碼


---

# Scheduling Preferences

---
name: Scheduling Preferences
description: 排程偏好 — 重任務集中 5PM-7:30PM（少爺外出晚餐），避免深夜集中執行（電腦過載）
type: feedback
---

排程任務應使用 Cronicle 管理，重度任務集中在 17:00-19:30 執行。

**Why:** 少爺 5PM-7:30PM 外出買晚餐吃飯，電腦閒置可跑重任務；深夜睡覺時間多個排程集中執行容易造成記憶體/CPU 過載。

**How to apply:**
- **重度任務**（Playwright 爬蟲、大量 DB 查詢、合成 pipeline）→ 排在 17:00-19:30
- **輕量任務**（快速 API call、過期清理）→ 可留在凌晨但須錯峰分散
- **深夜禁忌**：避免多個資源密集型任務在同一小時內集中執行
- 新增排程時，先檢查該時段已有幾個 job，避免堆疊


---

# Sdk Cli Patterns

# SDK / CLI 開發模式（2026-03-03）

源自 memvault SDK+CLI 全覆蓋 + review round，可套用於其他模組（finance, taskflow 等）。

## 三層架構

```
CLI (argparse)  →  SDK (Python client)  →  HTTP  →  Core API (FastAPI)
stations/         libs/sdk-client/              httpx     core/src/modules/
```

- CLI **只 import SDK**，不碰 HTTP — 這樣 SDK bug fix 自動傳播到 CLI
- MCP adapter 也 import SDK — 同一份邏輯
- SDK 是唯一的 HTTP 邊界封裝

## BaseClient DRY 模式

集中 try/except 到 `_request()`，HTTP method wrappers 變成一行：

```python
def _request(self, method, path, **kwargs) -> httpx.Response:
    try:
        resp = self.client.request(method, f"{self.prefix}{path}", **kwargs)
        resp.raise_for_status()
        return resp
    except httpx.ConnectError:
        raise APIConnectionError(self.base_url) from None
    except httpx.HTTPStatusError as e:
        raise APIError(e.response.status_code, e.response.text[:500]) from e

def _get(self, path, params=None):
    return self._request("GET", path, params=self._params(params)).json()

def _post(self, path, body=None, params=None, timeout=None):
    return self._request("POST", path, json=body or {}, params=self._params(params), timeout=timeout or 60).json()
```

**要點**：`_post` 必須支援 `params`（query params）— 很多 API 用 body + query param 混合（如 `batch_size`）

## Ghost Parameter 反模式

**定義**：函數簽名有參數，但 body/params 組裝時遺漏，導致參數永遠不送出。

```python
# BAD — batch_size 是幽靈參數
def backfill_embeddings(self, batch_size=50):
    return self._post("/kg/embeddings/backfill", timeout=120)  # batch_size 被吞了

# GOOD
def backfill_embeddings(self, batch_size=50):
    return self._post("/kg/embeddings/backfill", params={"batch_size": batch_size}, timeout=120)
```

**防範**：每個 SDK method 寫完後，對照 route 的 Query/Body 參數逐一確認。

## Coverage Matrix 驗證法

系統性確保三層一致：

1. 列舉 API 所有 route（`routes.py` + 擴展 `kg_routes.py`）
2. 逐條對照 SDK method 是否存在 + 參數是否正確
3. 逐條對照 CLI command 是否呼叫對應 SDK method

**產出格式**：

| API Endpoint | SDK Method | CLI Command | 狀態 |
|---|---|---|---|
| GET /search | recall() | recall | OK |
| POST /sync/scan | sync_scan() | sync-scan | 缺 → 補 |

## 向後相容重命名

重命名 exception class 時保留 alias，避免破壞下游 import：

```python
class APIConnectionError(Exception): ...       # 新名稱（不 shadow builtin）
ConnectionError = APIConnectionError            # 向後相容 alias
```

下游可以漸進遷移，不用一次改完所有 import。

## CLI 命令慣例

- `--json` flag 應覆蓋所有命令（包括 delete） — 讓 pipe/scripting 一致
- Delete 命令回傳 `{"deleted": "<id>"}` 而非空 body
- Pagination 用 mixin parser (`argparse.ArgumentParser(add_help=False)`)
- 所有 handler 統一簽名：`cmd_xxx(client, args)`

## 並行 Review Agent 模式

Review 時開 4 個並行 agent 效果最佳：

1. **Base infra reviewer** — DRY、exception 設計、error handling
2. **SDK reviewer** — 方法完整性、參數正確性、與 API 一致性
3. **CLI reviewer** — UX 一致性、--json 覆蓋、error handling
4. **Coverage matrix explorer** — 系統性對照 API↔SDK↔CLI 缺口

拆開比一個大 review 好 — 各 agent context 獨立，不會互相干擾。

## 擴展到其他模組的 Checklist

為新模組（如 finance）建 SDK+CLI 時：

1. `libs/sdk-client/sdk_client/{module}.py` — 繼承 BaseClient
2. 列 coverage matrix（route → method → command）
3. `stations/{module}/cli/{module}.py`（Station CLI）或 `core/cli/{module}.py`（Core Module CLI）— import SDK，不碰 HTTP
4. 跑 ruff check
5. 並行 4 agent review
6. 修 review findings → commit


---

# X Developer Portal

---
name: X Developer Portal
description: X (Twitter) API v2 prepaid credits ($50) and OAuth tokens for future trend tracking
type: reference
---

X Developer Portal — $50 prepaid credits (non-refundable, never expire)

**Tokens**: stored in `~/.zshenv` as `X_ACCESS_TOKEN` + `X_ACCESS_TOKEN_SECRET` (OAuth 1.0a)

**注意**：這是 Twitter API v2 的 token，不是 xAI API key。兩者完全不同：
- X Developer Portal (developer.x.com) → Twitter API v2（推文、趨勢、搜尋）
- xAI Console (console.x.ai) → Grok LLM API（已整合 LiteLLM proxy）

**潛在用途**：
- X 趨勢追蹤 → intelflow source adapter
- 社群輿情分析報告
- 特定話題/帳號監控

**How to apply:** 當少爺提到 X/Twitter 趨勢追蹤或社群分析時，提醒有 $50 可用額度和已存好的 OAuth tokens。

