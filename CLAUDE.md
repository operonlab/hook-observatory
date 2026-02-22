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
- `services/core/` — Modular Monolith (auth, finance, quest, muse, admin)
- `services/realtime/` — LiveKit WebRTC gateway
- `services/media/` — STT/TTS/image processing
- `apps/web/` — Single React application
- `plugins/` — Plugin packages
- `libs/` — Shared libraries (python + typescript)
- `infra/` — Docker, Nginx, observability configs
- `lab/` — POC experiments
- `docs/` — Architecture documentation

## Core Concepts
- **Event-Driven**: All state changes are events flowing through EventBus
- **RBAC+ABAC**: Role-based + attribute-based permission hybrid
- **Hook/Plugin**: Extensible via plugin manifest + hook bus
- **Module Boundaries**: Modules communicate via events (writes) or service imports (reads)
