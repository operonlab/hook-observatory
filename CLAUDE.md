---
doc_version: 5
content_hash: f6ad7751
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
- `core/` — Modular Monolith (10 Core Modules + hot-path services)
  - `core/src/modules/` — Domain modules (auth, finance, quest, muse, scout, lore, dojo, roster, nexus, admin)
  - `core/services/realtime/` — LiveKit WebRTC gateway
  - `core/services/media/` — STT/TTS/image processing
- `workbench/` — Single React application
- `mcp/` — MCP adapter layer (thin wrappers over Core API)
- `stations/` — Standalone local tools (system-monitor, llm-usage, envkit, tmux-webui, session-redactor, sandbox-executor)
- `vendor/` — Third-party community tools (observability)
- `bridges/` — External platform connectors (LINE, Telegram, Discord)
- `plugins/` — Plugin packages
- `libs/` — Shared libraries (python + typescript)
- `infra/` — Docker, Nginx, observability configs
- `scripts/` — Build/translate/deploy scripts
- `lab/` — POC experiments
- `docs/` — 架構 + 願景文件（繁體中文，source of truth）
  - `docs/vision/` — 平台願景（宣言、領域目錄、ADRs、路線圖）
  - `docs/architecture/` — 系統架構、ADRs、設計原則
- `docs-en/` — English backup (original English versions)

## Service Taxonomy
- **Foundation**: auth, admin
- **Domain Services** (DB-backed): finance, quest, muse, scout, lore, dojo, roster, nexus
- **Bridges**: External connectors (social-hooks, notification)
- **Hot-path Services**: media (STT/TTS/image), realtime (LiveKit)
- **Stations**: Standalone local tools (system-monitor, llm-usage, envkit, tmux-webui, session-redactor, sandbox-executor)
- **Vendor**: Third-party community tools (observability)
- **Compositions**: Service assemblies for specific use cases (Legal Advisor, Church Music, Virtual CS, ERP/POS)

## Core Concepts
- **LEGO Composition**: Services are reusable blocks. Projects = extend services + compose them. No "project vs module" distinction.
- **Event-Driven**: All state changes are events flowing through EventBus
- **RBAC+ABAC**: Role-based + attribute-based permission hybrid
- **Hook/Plugin**: Extensible via plugin manifest + hook bus
- **Module Boundaries**: Modules communicate via events (writes) or service imports (reads)
