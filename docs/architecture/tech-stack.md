# Technology Stack Specification

## Backend

| Component | Choice | Version | Rationale |
|-----------|--------|---------|-----------|
| Language | Python | 3.12+ | Ecosystem maturity, AI/ML integration |
| Framework | FastAPI | 0.115+ | Async-first, OpenAPI auto-gen, Pydantic native |
| Package Manager | uv | latest | Fast, workspace support, lockfile |
| ASGI Server | Uvicorn | 0.34+ | Production-grade, HTTP/2 support |
| Config | pydantic-settings | 2.0+ | Type-safe env config, `.env` loading |
| Logging | structlog | 24.0+ | Structured JSON logging, OTel integration |
| HTTP Client | httpx | 0.27+ | Async HTTP for external service calls |
| Event Bus | In-process async | -- | Module-to-module events (upgradeable to Redis Streams) |
| Hook Engine | Custom | -- | Plugin lifecycle hooks (before_*/after_*) |

## Frontend

| Component | Choice | Version | Rationale |
|-----------|--------|---------|-----------|
| Language | TypeScript | 5.x | Type safety, DX |
| Framework | React | 19 | Component model, ecosystem, concurrent features |
| Build Tool | Rsbuild | latest | Rspack-based, fast builds |
| Package Manager | pnpm | 9+ | Workspace support, disk efficient |
| Styling | Tailwind CSS | 4.x | Utility-first, consistent design tokens |
| State | Zustand | 5.x | Lightweight, per-module scoped |
| Routing | React Router | 7.x | Lazy loading, nested routes |

## Data Layer

### PostgreSQL (Primary Database)

- **Version**: 17+
- **Deployment**: Docker container, single instance
- **Schema isolation**: Each module owns its own schema (`CREATE SCHEMA <module_name>`)
- **Driver**: psycopg 3 (async support via psycopg[binary])
- **Migrations**: Raw SQL files in `services/core/migrations/`, version-tracked

```
PostgreSQL Instance
├── schema: auth         (users, sessions, permissions)
├── schema: finance      (transactions, budgets, subscriptions)
├── schema: quest        (quests, skills, rewards)
├── schema: muse         (sparks, links, graph)
└── schema: admin        (audit_logs, settings)
```

**Rules**:
- Module A must NEVER directly query Module B's schema
- Cross-module data access goes through service layer imports
- Shared reference data (e.g., user IDs) uses consistent types (UUID v7)

### Redis (Cache + Event Bus)

- **Version**: 7+
- **Deployment**: Docker container, single instance
- **Key prefix**: `<module>:` namespace (e.g., `finance:cache:`, `auth:session:`)

**Use cases**:

| Use Case | Pattern | Example |
|----------|---------|---------|
| Caching | GET/SET with TTL | `finance:cache:summary:{user_id}` |
| Session | Hash with expiry | `auth:session:{session_id}` |
| Event Bus | Streams (future) | `events:finance.transaction.created` |
| Rate limiting | INCR + EXPIRE | `auth:ratelimit:{ip}` |

### Object Storage (S3-Compatible)

- **Choice**: **RustFS** (MinIO community fork, Rust rewrite)
- **Interface**: S3-compatible API (boto3 or custom client)
- **Deployment**: Docker container
- **License**: AGPLv3

**Use cases**: File uploads, media storage, report exports, model artifacts.

## Realtime & Media

### LiveKit (WebRTC)

- **Version**: Latest (self-hosted)
- **Deployment**: Docker container + SSL/domain required
- **License**: Apache 2.0
- **Port**: 8830 (Realtime service)

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

| SDK | Language | Use |
|-----|----------|-----|
| livekit-server-sdk-python | Python | Token generation, room management |
| @livekit/components-react | React | UI components, hooks |
| livekit-agents | Python | AI voice/video pipelines |

### Streaming API (SSE)

For non-media real-time data (LLM responses, progress updates):

```python
from fastapi.responses import StreamingResponse

@app.get("/api/chat/stream")
async def chat_stream():
    async def generate():
        async for chunk in llm.stream():
            yield f"data: {chunk}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

**When to use what**:

| Need | Solution |
|------|----------|
| LLM streaming responses | SSE (Server-Sent Events) |
| Real-time voice/video | LiveKit WebRTC |
| Module-to-module events | In-process Event Bus |
| External service events | Redis Streams |
| Client notifications | SSE |
| File transfer | HTTP multipart upload → Object Storage |

## Observability

| Component | Dev | Prod | Purpose |
|-----------|-----|------|---------|
| Collector | grafana/otel-lgtm | SigNoz OTel Collector | Ingest traces, metrics, logs |
| Traces | Grafana Tempo | SigNoz | Distributed tracing |
| Metrics | Grafana + Prometheus | SigNoz | Application metrics |
| Logs | Grafana Loki | SigNoz | Structured log aggregation |
| Dashboards | Grafana | SigNoz | Visualization |

**Integration**: FastAPI + structlog → OpenTelemetry SDK → OTel Collector → Backend

See [Observability](./observability.md) for architecture details.

## Hook/Plugin System

| Component | Implementation | Purpose |
|-----------|---------------|---------|
| Hook Engine | Custom Python | Lifecycle hooks (before_*/after_*) |
| Plugin Manifest | `pulso-plugin.json` | Plugin declaration, permissions |
| Plugin Runtime | Sandboxed execution | Isolated plugin code execution |
| UI Slots | React PluginSlot | Frontend plugin injection points |

See [Plugin System](./plugin-system.md) for specification.
