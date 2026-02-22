# Technology Stack Specification

## Backend

| Component | Choice | Version | Rationale |
|-----------|--------|---------|-----------|
| Language | Python | 3.12+ | Ecosystem maturity, AI/ML integration |
| Framework | FastAPI | 0.115+ | Async-first, OpenAPI auto-gen, Pydantic native |
| Package Manager | uv | latest | Fast, workspace support, lockfile |
| ASGI Server | Uvicorn | 0.34+ | Production-grade, HTTP/2 support |
| Config | pydantic-settings | 2.0+ | Type-safe env config, `.env` loading |
| Logging | structlog | 24.0+ | Structured JSON logging, async compatible |
| HTTP Client | httpx | 0.27+ | Async HTTP for inter-service calls |

## Frontend

| Component | Choice | Version | Rationale |
|-----------|--------|---------|-----------|
| Language | TypeScript | 5.x | Type safety, DX |
| Framework | React | 19 | Component model, ecosystem, concurrent features |
| Build Tool | Rsbuild | latest | Rspack-based, Module Federation v2 native |
| Package Manager | pnpm | 9+ | Workspace support, disk efficient |
| Styling | Tailwind CSS | 4.x | Utility-first, no CSS conflicts across MFEs |
| State | Zustand | 5.x | Lightweight, per-MFE scoped |
| Routing | React Router | 7.x | Per-MFE routing |

## Data Layer

### PostgreSQL (Primary Database)

- **Version**: 17+
- **Deployment**: Docker container, single instance
- **Schema isolation**: Each service owns its own schema (`CREATE SCHEMA <service_name>`)
- **Driver**: psycopg 3 (async support via psycopg[binary])
- **Migrations**: Raw SQL files in `services/<name>/migrations/`, version-tracked

```
PostgreSQL Instance
├── schema: gateway      (auth, sessions, app_registry)
├── schema: finance      (transactions, budgets, subscriptions)
├── schema: quest        (quests, skills, rewards)
├── schema: muse         (sparks, links, graph)
└── schema: research     (reports, sources)
```

**Rules**:
- Service A must NEVER directly query Service B's schema
- Cross-service data access goes through HTTP API
- Shared reference data (e.g., user IDs) uses consistent types (UUID v7)

### Redis (Cache + Pub/Sub)

- **Version**: 7+
- **Deployment**: Docker container, single instance
- **Key prefix**: `<service>:` namespace (e.g., `finance:cache:`, `quest:events:`)

**Use cases**:

| Use Case | Pattern | Example |
|----------|---------|---------|
| Caching | GET/SET with TTL | `finance:cache:summary:{user_id}` |
| Session | Hash with expiry | `gateway:session:{session_id}` |
| Pub/Sub | PUBLISH/SUBSCRIBE | `events:finance:transaction_created` |
| Rate limiting | INCR + EXPIRE | `gateway:ratelimit:{ip}` |
| Task queue | Stream / List | `orchestrator:tasks` |

### Object Storage (S3-Compatible)

- **Current evaluation**: Garage (Deuxfleurs) or SeaweedFS
- **MinIO status**: Archived Feb 2026, no longer maintained
- **Interface**: S3-compatible API (boto3 or custom client)
- **Deployment**: Docker container

**Decision**: **RustFS** — MinIO 社群 fork（Rust 重寫），API 完全相容，活躍維護。

| Name | License | Status | Note |
|------|---------|--------|------|
| RustFS | AGPLv3 | Active (MinIO fork) | Drop-in replacement, community-driven |
| Garage | AGPLv3 | Active | Lightweight alternative |
| SeaweedFS | Apache 2.0 | Active | High performance alternative |
| MinIO | AGPLv3 | Archived (Feb 2026) | No longer maintained |

**Use cases**: File uploads, media storage, report exports, model artifacts.

## Realtime & Media

### LiveKit (WebRTC)

- **Version**: Latest (self-hosted)
- **Deployment**: Docker container + SSL/domain required
- **License**: Apache 2.0

**Architecture**:
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

**Use cases**:
- Voice assistant (STT → LLM → TTS pipeline via Agents)
- Video streaming (avatar, screen share)
- Real-time audio processing

### Streaming API (SSE)

For non-media real-time data (LLM responses, progress updates):

```python
# Backend: FastAPI StreamingResponse
from fastapi.responses import StreamingResponse

@app.get("/api/chat/stream")
async def chat_stream():
    async def generate():
        async for chunk in llm.stream():
            yield f"data: {chunk}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

```typescript
// Frontend: EventSource or fetch + ReadableStream
const response = await fetch("/api/chat/stream");
const reader = response.body.getReader();
```

**When to use what**:

| Need | Solution |
|------|----------|
| LLM streaming responses | SSE (Server-Sent Events) |
| Real-time voice/video | LiveKit WebRTC |
| Service-to-service events | Redis Pub/Sub |
| Client notifications | SSE or WebSocket (Socket.IO) |
| File transfer | HTTP multipart upload → Object Storage |
