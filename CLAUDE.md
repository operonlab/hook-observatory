# Workshop

Micro services + micro frontend workspace (v2).

## Stack
- **Backend**: Python 3.12 / FastAPI / uv
- **Frontend**: React 19 / TypeScript / Rsbuild / pnpm
- **Database**: PostgreSQL (per-service schema isolation)
- **Cache/Pubsub**: Redis
- **Object Storage**: RustFS (MinIO fork, S3-compatible)
- **Realtime**: LiveKit (WebRTC for voice/video), SSE (streaming API)
- **Inter-service**: Redis Pub/Sub (events), HTTP (queries)

## Structure
- `services/` — Python micro services
- `apps/` — React micro frontends
- `libs/` — Shared libraries (python + typescript)
- `infra/` — Docker, Nginx, scripts
- `lab/` — POC experiments (Skill outputs, prototypes)
- `docs/` — Cross-domain documentation

## Conventions
- See `docs/architecture/folder-structure.md` for naming rules
- Service naming: kebab-case dirs, snake_case Python packages
- Each service exposes `GET /health`
- Domain docs in each service/app `README.md`; cross-domain docs in `docs/`
