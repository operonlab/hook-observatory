---
doc_version: 3
content_hash: 1db2d231
source_version: 3
translated_at: 2026-02-23
---

# Workshop

Modular Monolith + Event-Driven 工作區。

## Stack
- **Backend**: Python 3.12 / FastAPI / uv (Modular Monolith)
- **Frontend**: React 19 / TypeScript / Rsbuild / pnpm (Single App)
- **Database**: PostgreSQL (每個模組的 schema 隔離)
- **Cache/Events**: Redis (cache + event bus)
- **Object Storage**: RustFS (MinIO 分支，相容 S3)
- **Realtime**: LiveKit (語音/視訊的 WebRTC), SSE (streaming)
- **Observability**: OpenTelemetry + LGTM (dev) / SigNoz (prod)

## Structure
- `core/` — Modular Monolith (10 Core Modules + hot-path services)
  - `core/src/modules/` — Domain modules (auth, finance, quest, muse, intel, memory, skill, workforce, matching, admin)
  - `core/services/realtime/` — LiveKit WebRTC gateway
  - `core/services/media/` — STT/TTS/image processing
- `dashboard/` — 單一 React 應用程式
- `mcp/` — MCP adapter layer (核心 API 的薄封裝)
- `stations/` — 獨立本地工具 (disk analyzer, LLM usage 等)
- `bridges/` — 外部平台連接器 (LINE, Telegram, Discord)
- `plugins/` — 插件套件
- `libs/` — 共享函式庫 (python + typescript)
- `infra/` — Docker, Nginx, observability 配置
- `scripts/` — 建置/翻譯/部署腳本
- `lab/` — POC 實驗
- `docs/` — 架構 + 願景文件
  - `docs/vision/` — 平台願景 (manifesto, domain catalog, ADRs, roadmap)
  - `docs/zh-TW/` — 繁體中文翻譯 (自動生成)

## Three-Tier Taxonomy
- **Core Modules** (資料庫驅動): auth, finance, quest, muse, intel, memory, skill, workforce, matching, admin
- **Stations**: 獨立本地工具 (legal advisor, church music 等)
- **Bridges**: 外部連接器 (LINE, Telegram, Discord, Firebase)

## Core Concepts
- **Event-Driven**: 所有狀態變更均為流經 EventBus 的事件
- **RBAC+ABAC**: 基於角色與屬性權限的混合機制
- **Hook/Plugin**: 透過 plugin manifest + hook bus 實現擴充
- **Module Boundaries**: 模組透過事件 (writes) 或服務匯入 (reads) 進行通訊
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
