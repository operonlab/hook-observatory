---
doc_version: 5
content_hash: pending
source_version: 4
target_lang: zh-TW
translated_at: 2026-03-04
---

# 技術棧規範 (Technology Stack Specification)

## 後端 (Backend)

| 組件 | 選擇 | 版本 | 理由 |
|-----------|--------|---------|-----------|
| 語言 | Python | 3.12+ | AI/ML 生態系原生支援、開發速度最大化、AI 程式碼生成品質最佳（詳見 [AD-9](./architecture-decisions.md#ad-9-python-first--selective-rust)） |
| 框架 | FastAPI | 0.115+ | 非同步優先，OpenAPI 自動生成，原生支援 Pydantic |
| 套件管理工具 | uv | latest | 快速，支援 workspace，具有 lockfile |
| ASGI 伺服器 | Uvicorn | 0.34+ | 生產級別，支援 HTTP/2 |
| 配置 | pydantic-settings | 2.0+ | 型別安全的環境變數配置，支援 `.env` 載入 |
| 日誌 | structlog | 24.0+ | 結構化 JSON 日誌，OTel 整合 |
| HTTP 用戶端 | httpx | 0.27+ | 用於外部服務調用的非同步 HTTP |
| 事件匯流排 | In-process async + Redis Streams | -- | 模組間事件（`CORE_EVENT_BACKEND=redis` 啟用 Redis Streams） |
| 掛鉤引擎 | Custom | -- | 插件生命週期掛鉤 (before_*/after_*) |

## 前端 (Frontend)

| 組件 | 選擇 | 版本 | 理由 |
|-----------|--------|---------|-----------|
| 語言 | TypeScript | 5.x | 型別安全，開發體驗 (DX) |
| 框架 | React | 19 | 組件模型，生態系統，並發特性 (concurrent features) |
| 建置工具 | Rsbuild | latest | 基於 Rspack，建置速度快 |
| 套件管理工具 | pnpm | 9+ | 支援 workspace，磁碟效率高 |
| 樣式 | Tailwind CSS | 4.x | 功能類優先 (Utility-first)，一致的設計標記 (design tokens) |
| 狀態管理 | Zustand | 5.x | 輕量級，基於模組作用域 |
| 路由 | React Router | 7.x | 延遲載入 (Lazy loading)，巢狀路由 |

## 資料層 (Data Layer)

### PostgreSQL (主要資料庫)

- **版本**: 17+
- **部署**: Docker 容器，單一實例
- **Schema 隔離**: 每個模組擁有自己的 schema (`CREATE SCHEMA <module_name>`)
- **驅動程式**: psycopg 3 (透過 psycopg[binary] 支援非同步)
- **遷移**: `core/migrations/` 中的原始 SQL 檔案，版本追蹤

```
PostgreSQL Instance
├── schema: auth         (users, sessions, spaces, permissions)     — 第一階段 (Phase 1)
├── schema: admin        (audit_logs, settings, system health)      — 第一階段 (Phase 1)
├── schema: finance      (transactions, budgets, subscriptions)     — 第一階段 (Phase 1)
├── schema: taskflow     (quests, tasks, dispatch, rewards)         — 第一階段 (Phase 1)
├── schema: ideagraph    (sparks, links, knowledge graph)           — 第一階段 (Phase 1)
├── schema: capture      (captures, enrichment, promotion)          — 第一階段 (Phase 1)
├── schema: briefing     (briefings, templates, schedules)          — 第二階段 (Phase 2)
├── schema: dailyos      (daily routines, habits, strategies)       — 第二階段 (Phase 2)
├── schema: intelflow    (feeds, briefings, topic tracking)         — 第二階段 (Phase 2)
├── schema: memvault     (memories, embeddings, profiles)           — 第二階段 (Phase 2)
├── schema: skillpath    (skill trees, learning paths, assessments) — 第二階段 (Phase 2)
├── schema: nodeflow     (workflows, DAG nodes, execution runs)     — 第二階段 (Phase 2)
├── schema: notification (preferences, log, channels, rules)        — 第二階段 (Phase 2)
├── schema: invest       (portfolios, transactions, analysis)       — 第二階段 (Phase 2)
├── schema: paper        (papers, digests, arXiv metadata)          — 第二階段 (Phase 2)
├── schema: workpool     (resources, schedules, capacity)           — 第三階段 (Phase 3)
└── schema: matchcore    (match rules, scores, recommendations)     — 第三階段 (Phase 3)
```

**規則**:
- 模組 A 絕對禁止直接查詢模組 B 的 schema
- 跨模組資料存取必須透過服務層 (service layer) 導入
- 共享參考資料（例如：user IDs）使用一致的型別 (UUID v7)

### Redis (快取 + 事件匯流排)

- **版本**: 7+
- **部署**: Docker 容器，單一實例
- **鍵前綴**: `<module>:` 命名空間（例如：`finance:cache:`, `auth:session:`）

**使用場景**:

| 使用場景 | 模式 | 範例 |
|----------|---------|---------|
| 快取 | 帶有 TTL 的 GET/SET | `finance:cache:summary:{user_id}` |
| 會話 (Session) | 帶有過期時間的 Hash | `auth:session:{session_id}` |
| 事件匯流排 | Streams (未來) | `events:finance.transaction.created` |
| 速率限制 | INCR + EXPIRE | `auth:ratelimit:{ip}` |

### 物件儲存 (S3 相容)

- **選擇**: **RustFS** (MinIO 社群分支，以 Rust 重寫)
- **介面**: S3 相容 API (boto3 或自定義用戶端)
- **部署**: Docker 容器
- **授權**: AGPLv3

**使用場景**: 檔案上傳、媒體儲存、報表匯出、模型產出物。

## 即時通訊與媒體 (Realtime & Media)

### LiveKit (WebRTC)

- **版本**: 最新 (自託管)
- **部署**: 需要 Docker 容器 + SSL/網域
- **授權**: Apache 2.0
- **連接埠**: 未部署（LiveKit 規劃中，尚未註冊至 port_registry）

```
Browser (React SDK)
    ↕ WebRTC (wss://)
LiveKit Server (SFU)
    ↕ gRPC
LiveKit Agents (Python)
    ↕ HTTP
AI Services (STT, LLM, TTS)
```

**SDKs**:

| SDK | 語言 | 用途 |
|-----|----------|-----|
| livekit-server-sdk-python | Python | 令牌生成，房間管理 |
| @livekit/components-react | React | UI 組件，hooks |
| livekit-agents | Python | AI 語音/影片管線 |

### 串流 API (SSE)

用於非媒體類即時數據（LLM 回應、進度更新）：

```python
from fastapi.responses import StreamingResponse

 @app.get("/api/chat/stream")
async def chat_stream():
    async def generate():
        async for chunk in llm.stream():
            yield f"data: {chunk}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

**方案選擇建議**:

| 需求 | 解決方案 |
|------|----------|
| LLM 串流回應 | SSE (Server-Sent Events) |
| 即時語音/影片 | LiveKit WebRTC |
| 模組間事件 | 進程內事件匯流排 (In-process Event Bus) |
| 外部服務事件 | Redis Streams |
| 用戶端通知 | SSE |
| 檔案傳輸 | HTTP multipart 上傳 → 物件儲存 |

## 可觀測性 (Observability)

| 組件 | 開發環境 (Dev) | 生產環境 (Prod) | 目的 |
|-----------|-----|------|---------|
| 收集器 | grafana/otel-lgtm | SigNoz OTel Collector | 攝取追蹤 (traces)、指標 (metrics)、日誌 (logs) |
| 追蹤 (Traces) | Grafana Tempo | SigNoz | 分散式追蹤 |
| 指標 (Metrics) | Grafana + Prometheus | SigNoz | 應用程式指標 |
| 日誌 (Logs) | Grafana Loki | SigNoz | 結構化日誌聚合 |
| 儀表板 | Grafana | SigNoz | 視覺化 |

**整合**: FastAPI + structlog → OpenTelemetry SDK → OTel Collector → 後端

架構詳情請參閱 [可觀測性 (Observability)](./observability.md)。

## 掛鉤/插件系統 (Hook/Plugin System)

| 組件 | 實作方式 | 目的 |
|-----------|---------------|---------|
| 掛鉤引擎 | 自定義 Python | 生命週期掛鉤 (before_*/after_*) |
| 插件清單 | `plugin.json` | 插件聲明、權限 |
| 插件運行時 | 沙盒執行 (Sandboxed execution) | 隔離的插件程式碼執行 |
| UI 插槽 | React PluginSlot | 前端插件注入點 |

規範詳情請參閱 [插件系統 (Plugin System)](./plugin-system.md)。

## 微服務層 (Microservices Layer)

從 Core 單體漸進拆出的獨立部署模組。選定條件：零跨模組依賴、可獨立運行。

| 模組 | Port | 狀態 |
|------|------|------|
| paper | 10010 | ✅ 已拆出 |
| intelflow | 10011 | ✅ 已拆出 |
| invest | 10012 | ✅ 已拆出 |

共享 PostgreSQL + Redis，以獨立 FastAPI 進程運行，Nginx 反向代理路由。

## 多機部署 (Multi-Machine Deployment)

| 組件 | 選擇 | 用途 |
|------|------|------|
| VPN | Tailscale | 跨機安全連線 |
| 部署管理 | Komodo | 容器部署、服務編排（Docker Compose 遠端管理） |
| 任務調度 | Fleet Station | 遠端運算節點任務分派 |

**架構**：Mac 主機（Core + 全部 Stations）+ 遠端 Windows 節點（GPU 運算任務），透過 Tailscale VPN 連線，Komodo 管理容器生命週期。

## 連接埠慣例 (Port Convention)

所有自管服務使用 10000+ 範圍，單一真值源：`libs/sdk-client/sdk_client/port_registry.py`。

| 範圍 | 用途 |
|------|------|
| 10000-10099 | Core 服務 |
| 10100-10199 | 工作站：基礎建設 & 營運 |
| 10200-10299 | 工作站：AI & 媒體 |
| 10300-10399 | 工作站：商業 & 工具 |
| 10500-10599 | 前端 |

第三方 / Docker 服務保留原始埠號（PostgreSQL 5432, Redis 6379, Qdrant 6333 等）。
