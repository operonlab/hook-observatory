---
doc_version: 3
content_hash: 1db2d231
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
  - `core/src/modules/` — Domain modules (auth, finance, quest, muse, intel, memory, skill, workforce, matching, admin)
  - `core/services/realtime/` — LiveKit WebRTC gateway
  - `core/services/media/` — STT/TTS/image processing
- `dashboard/` — Single React application
- `mcp/` — MCP adapter layer (thin wrappers over Core API)
- `stations/` — Standalone local tools (disk analyzer, LLM usage, etc.)
- `bridges/` — External platform connectors (LINE, Telegram, Discord)
- `plugins/` — Plugin packages
- `libs/` — Shared libraries (python + typescript)
- `infra/` — Docker, Nginx, observability configs
- `scripts/` — Build/translate/deploy scripts
- `lab/` — POC experiments
- `docs/` — Architecture + vision documentation
  - `docs/vision/` — Platform vision (manifesto, domain catalog, ADRs, roadmap)
  - `docs/zh-TW/` — Traditional Chinese translations (auto-generated)

## Three-Tier Taxonomy
- **Core Modules** (DB-backed): auth, finance, quest, muse, intel, memory, skill, workforce, matching, admin
- **Stations**: Standalone local tools (legal advisor, church music, etc.)
- **Bridges**: External connectors (LINE, Telegram, Discord, Firebase)

## Core Concepts
- **Event-Driven**: All state changes are events flowing through EventBus
- **RBAC+ABAC**: Role-based + attribute-based permission hybrid
- **Hook/Plugin**: Extensible via plugin manifest + hook bus
- **Module Boundaries**: Modules communicate via events (writes) or service imports (reads)
