---
doc_version: 3
content_hash: 95d02640
source_version: 3
target_lang: en
translated_at: 2026-02-24
source_hash: 638cc42f
source_lang: zh-TW
---

# Technology Stack Specification

## Backend

| Component | Choice | Version | Reason |
|-----------|--------|---------|-----------|
| Language | Python | 3.12+ | Ecosystem maturity, AI/ML integration |
| Framework | FastAPI | 0.115+ | Async-first, automatic OpenAPI generation, native Pydantic support |
| Package Manager | uv | latest | Fast, supports workspaces, with lockfile |
| ASGI Server | Uvicorn | 0.34+ | Production-grade, supports HTTP/2 |
| Configuration | pydantic-settings | 2.0+ | Type-safe environment variable configuration, supports `.env` loading |
| Logging | structlog | 24.0+ | Structured JSON logging, OTel integration |
| HTTP Client | httpx | 0.27+ | Asynchronous HTTP for external service calls |
| Event Bus | In-process async | -- | Inter-module events (upgradeable to Redis Streams) |
| Hook Engine | Custom | -- | Plugin lifecycle hooks (before_*/after_*) |

## Frontend

| Component | Choice | Version | Reason |
|-----------|--------|---------|-----------|
| Language | TypeScript | 5.x | Type safety, developer experience (DX) |
| Framework | React | 19 | Component model, ecosystem, concurrent features |
| Build Tool | Rsbuild | latest | Based on Rspack, fast build speed |
| Package Manager | pnpm | 9+ | Supports workspaces, high disk efficiency |
| Styling | Tailwind CSS | 4.x | Utility-first, consistent design tokens |
| State Management | Zustand | 5.x | Lightweight, module-scoped |
| Routing | React Router | 7.x | Lazy loading, nested routing |

## Data Layer

### PostgreSQL (Main Database)

- **Version**: 17+
- **Deployment**: Docker container, single instance
- **Schema Isolation**: Each module has its own schema (`CREATE SCHEMA <module_name>`)
- **Driver**: psycopg 3 (supports async via psycopg[binary])
- **Migrations**: Raw SQL files in `core/migrations/`, version tracking

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
- Cross-module data access must be implemented through the service layer
- Shared reference data (e.g., user IDs) use consistent types (UUID v7)

### Redis (Cache + Event Bus)

- **Version**: 7+
- **Deployment**: Docker container, single instance
- **Key Prefix**: `<module>:` namespace (e.g., `finance:cache:`, `auth:session:`)

**Use Cases**:

| Use Case | Pattern | Example |
|----------|---------|---------|
| Cache | GET/SET with TTL | `finance:cache:summary:{user_id}` |
| Session | Hash with expiration | `auth:session:{session_id}` |
| Event Bus | Streams (future) | `events:finance.transaction.created` |
| Rate Limiting | INCR + EXPIRE | `auth:ratelimit:{ip}` |

### Object Storage (S3 Compatible)

- **Choice**: **RustFS** (MinIO community fork, rewritten in Rust)
- **Interface**: S3 compatible API (boto3 or custom client)
- **Deployment**: Docker container
- **License**: AGPLv3

**Use Cases**: File uploads, media storage, report exports, model outputs.

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
| livekit-agents | Python | AI voice/video pipeline |

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

**Recommended Solution Choices**:

| Requirement | Solution |
|------|----------|
| LLM Streaming Response | SSE (Server-Sent Events) |
| Real-time Voice/Video | LiveKit WebRTC |
| Inter-module Events | In-process Event Bus |
| External Service Events | Redis Streams |
| Client Notifications | SSE |
| File Transfer | HTTP multipart upload → Object storage |

## Observability

| Component | Development Environment (Dev) | Production Environment (Prod) | Purpose |
|-----------|-----|------|---------|
| Collector | grafana/otel-lgtm | SigNoz OTel Collector | Ingests traces, metrics, logs |
| Traces | Grafana Tempo | SigNoz | Distributed Tracing |
| Metrics | Grafana + Prometheus | SigNoz | Application Metrics |
| Logs | Grafana Loki | SigNoz | Structured Log Aggregation |
| Dashboard | Grafana | SigNoz | Visualization |

**Integration**: FastAPI + structlog → OpenTelemetry SDK → OTel Collector → Backend

For architecture details, refer to [Observability](./observability.md).

## Hook/Plugin System

| Component | Implementation Method | Purpose |
|-----------|---------------|---------|
| Hook Engine | Custom Python | Lifecycle hooks (before_*/after_*) |
| Plugin List | `plugin.json` | Plugin declaration, permissions |
| Plugin Runtime | Sandboxed execution | Isolated plugin code execution |
| UI Slots | React PluginSlot | Frontend plugin injection point |

For specification details, refer to [Plugin System](./plugin-system.md).
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2766ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2896ms
