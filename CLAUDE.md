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
- **SDK Clients**: `libs/python/src/workshop/clients/` — unified Python SDK layer for all services (20+ clients)

## Core Concepts
- **LEGO Composition**: Services are reusable blocks. Projects = extend services + compose them. No "project vs module" distinction.
- **Event-Driven**: All state changes are events flowing through EventBus
- **RBAC+ABAC**: Role-based + attribute-based permission hybrid
- **Hook/Plugin**: Extensible via plugin manifest + hook bus
- **Module Boundaries**: Modules communicate via events (writes) or service imports (reads)
```
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3389ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3388ms
