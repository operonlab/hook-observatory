---
doc_version: 3
content_hash: 95d02640
source_version: 3
target_lang: en
translated_at: 2026-02-24
source_hash: d5b1c604
source_lang: zh-TW
---

# Technology Stack Specification

## Backend

| Component | Choice | Version | Reason |
|-----------|--------|---------|-----------|
| Language | Python | 3.12+ | Native support for AI/ML ecosystem, maximized development speed, best quality for AI code generation (see [AD-9](./architecture-decisions.md#ad-9-python-first--selective-rust)) |
| Framework | FastAPI | 0.115+ | Async-first, automatic OpenAPI generation, native Pydantic support |
| Package Manager | uv | latest | Fast, supports workspaces, has a lockfile |
| ASGI Server | Uvicorn | 0.34+ | Production-grade, supports HTTP/2 |
| Configuration | pydantic-settings | 2.0+ | Type-safe environment variable configuration, supports .env loading |
| Logging | structlog | 24.0+ | Structured JSON logging, OTel integration |
| HTTP Client | httpx | 0.27+ | Asynchronous HTTP for external service calls |
| Event Bus | In-process async | -- | In-process async for inter-module events (upgradable to Redis Streams) |
| Hook Engine | Custom | -- | Plugin lifecycle hooks (before_*/after_*) |

## Frontend

| Component | Choice | Version | Reason |
|-----------|--------|---------|-----------|
| Language | TypeScript | 5.x | Type safety, developer experience (DX) |
| Framework | React | 19 | Component model, ecosystem, concurrent features |
| Build Tool | Rsbuild | latest | Based on Rspack, fast build speeds |
| Package Manager | pnpm | 9+ | Supports workspaces, disk-efficient |
| Styling | Tailwind CSS | 4.x | Utility-first, consistent design tokens |
| State Management | Zustand | 5.x | Lightweight, module-scoped |
| Routing | React Router | 7.x | Lazy loading, nested routing |

## Data Layer

### PostgreSQL (Primary Database)

- **Version**: 17+
- **Deployment**: Docker container, single instance
- **Schema Isolation**: Each module has its own schema (`CREATE SCHEMA <module_name>`)
- **Driver**: psycopg 3 (async support via psycopg[binary])
- **Migrations**: Raw SQL files in `core/migrations/`, version tracked

```
PostgreSQL Instance
├── schema: auth         (users, sessions, spaces, permissions)     — Phase 1
├── schema: finance      (transactions, budgets, subscriptions)     — Phase 1
├── schema: quest        (quests, tasks, dispatch, rewards)         — Phase 1
├── schema: muse         (sparks, links, knowledge graph)           — Phase 1
├── schema: scout        (feeds, briefings, topic tracking)         — Phase 2
├── schema: lore         (memories, embeddings, profiles)           — Phase 2
├── schema: dojo         (skill trees, learning paths, assessments) — Phase 2
├── schema: roster       (resources, schedules, capacity)           — Phase 3
├── schema: nexus        (match rules, scores, recommendations)     — Phase 3
└── schema: admin        (audit_logs, settings, system health)      — Phase 1
```

**Rules**:
- Module A is strictly forbidden from directly querying Module B's schema
- Cross-module data access must be routed through the service layer
- Shared reference data (e.g., user IDs) use a consistent type (UUID v7)

### Redis (Cache + Event Bus)

- **Version**: 7+
- **Deployment**: Docker container, single instance
- **Key Prefix**: `<module>:` namespace (e.g., `finance:cache:`, `auth:session:`)

**Use Cases**:

| Use Case | Pattern | Example |
|----------|---------|---------|
| Caching | GET/SET with TTL | `finance:cache:summary:{user_id}` |
| Session | Hash with expiration | `auth:session:{session_id}` |
| Event Bus | Streams (future) | `events:finance.transaction.created` |
| Rate Limiting | INCR + EXPIRE | `auth:ratelimit:{ip}` |

### Object Storage (S3 Compatible)

- **Choice**: **RustFS** (MinIO community fork, rewritten in Rust)
- **Interface**: S3 compatible API (boto3 or custom client)
- **Deployment**: Docker container
- **License**: AGPLv3

**Use Cases**: File uploads, media storage, report exports, model artifacts.

## Realtime & Media

### LiveKit (WebRTC)

- **Version**: Latest (self-hosted)
- **Deployment**: Requires Docker container + SSL/domain
- **License**: Apache 2.0
- **Port**: 8830 (realtime service)

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

| SDK | Language | Purpose |
|-----|----------|-----|
| livekit-server-sdk-python | Python | Token generation, room management |
| @livekit/components-react | React | UI components, hooks |
| livekit-agents | Python | AI voice/video pipelines |

### Streaming API (SSE)

For non-media realtime data (LLM responses, progress updates):

```python
from fastapi.responses import StreamingResponse

 @app.get("/api/chat/stream")
async def chat_stream():
    async def generate():
        async for chunk in llm.stream():
            yield f"data: {chunk}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

**Solution Selection Advice**:

| Requirement | Solution |
|------|----------|
| LLM Streaming Responses | SSE (Server-Sent Events) |
| Realtime Voice/Video | LiveKit WebRTC |
| Inter-module Events | In-process Event Bus |
| External Service Events | Redis Streams |
| Client-side Notifications | SSE |
| File Transfer | HTTP multipart upload → Object Storage |

## Observability

| Component | Development (Dev) | Production (Prod) | Purpose |
|-----------|-----|------|---------|
| Collector | grafana/otel-lgtm | SigNoz OTel Collector | Ingest traces, metrics, logs |
| Traces | Grafana Tempo | SigNoz | Distributed tracing |
| Metrics | Grafana + Prometheus | SigNoz | Application metrics |
| Logs | Grafana Loki | SigNoz | Structured log aggregation |
| Dashboards | Grafana | SigNoz | Visualization |

**Integration**: FastAPI + structlog → OpenTelemetry SDK → OTel Collector → Backend

For architectural details, see [Observability](./observability.md).

## Hook/Plugin System

| Component | Implementation | Purpose |
|-----------|---------------|---------|
| Hook Engine | Custom Python | Lifecycle hooks (before_*/after_*) |
| Plugin Manifest | `plugin.json` | Plugin declaration, permissions |
| Plugin Runtime | Sandboxed execution | Isolated plugin code execution |
| UI Slot | React PluginSlot | Frontend plugin injection point |

For specification details, see [Plugin System](./plugin-system.md).
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3576ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3256ms
