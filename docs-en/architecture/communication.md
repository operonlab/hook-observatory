---
doc_version: 1
content_hash: b6f7fdd7
source_version: 1
target_lang: en
translated_at: 2026-02-24
source_hash: 15be724d
source_lang: zh-TW
---

# Communication Patterns

## Overview

```
┌──────────────────────────────────────────────────────────┐
│  Browser (Single React App)                              │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ Layer 3: LLM Chat Overlay (SSE streaming)           │ │
│  ├─────────────────────────────────────────────────────┤ │
│  │ Layer 2: Dashboard Widgets  │  Layer 1: Module SPA  │ │
│  └─────────────────────────────────────────────────────┘ │
│  HTTP/SSE ──────────┐           WebRTC ──────────┐       │
└─────────────────────┼───────────────────────────┼───────┘
                      ▼                           ▼
              ┌──────────────┐           ┌──────────────┐
              │   Nginx      │           │   LiveKit    │
              │   Gateway    │           │   Server     │
              └──────┬───────┘           └──────┬───────┘
                     │                          │
                     ▼                          ▼
        ┌────────────────────────┐     ┌──────────────┐
        │    Core Monolith       │     │   Realtime   │
        │   ┌──────┬──────┐     │     │   Agents     │
        │   │auth  │quest │     │     └──────┬───────┘
        │   ├──────┼──────┤     │            │
        │   │finance│muse │     │     ┌──────┴───────┐
        │   └──────┴──────┘     │     │    Media     │
        │         │             │     │  (STT/TTS)   │
        │    Event Bus          │     └──────────────┘
        └───────┬───────────────┘
                │
          ┌─────┴─────┐
          │   Redis   │ (Cache + Events)
          └─────┬─────┘
                │
          ┌─────┴─────┐
          │ PostgreSQL│ (Per-schema)
          └───────────┘
```

## 1. Frontend → Backend: HTTP + Streaming

### Standard Request/Response

All frontend-to-backend communication goes through the Nginx reverse proxy to the Core Monolith, using **HTTP REST**.

```
Browser → https://domain.com/api/finance/transactions → Nginx → Core Monolith
```

**Conventions**:
- `GET` for reading, `POST` for creation, `PUT` for full updates, `PATCH` for partial updates, `DELETE` for deletion
- Request/response bodies use JSON format (keys use camelCase for JS compatibility)
- Pagination: use `?page=1&limit=20` with `X-Total-Count` header
- Error handling: use `{ "detail": "message" }` with appropriate HTTP status codes

### Streaming (SSE)

For long-running operations or LLM responses, **Server-Sent Events** are used:

```
Browser → GET /api/chat/stream (Accept: text/event-stream) → Nginx → Core
         ← data: {"chunk": "Hello"}\n\n
         ← data: {"chunk": " world"}\n\n
         ← data: [DONE]\n\n
```

**When to use SSE vs. WebSocket:**

| Standard | SSE | WebSocket |
|----------|-----|-----------|
| Direction | Server → Client (unidirectional) | Bidirectional |
| Use Case | LLM streaming, progress updates | Chat, real-time collaboration |
| Reconnection | Built-in automatic reconnection | Requires manual implementation |
| Via Proxy | Directly via Nginx/CDN | Requires `Upgrade` support |
| Complexity | Simple | More complex |

**Default choice: SSE** -- Meets 90% of streaming needs with lower complexity.

### File Upload

```
Browser → POST /api/storage/upload (multipart/form-data) → Nginx → Core → Object Store
```

## 2. Frontend ↔ LiveKit: WebRTC

For real-time audio and video, **LiveKit** (an independent Realtime service) is used.

```
                   ┌─────────────┐
                   │   Browser   │
                   │ (React SDK) │
                   └──────┬──────┘
                     WebRTC│wss://
                   ┌──────┴──────┐
                   │  LiveKit    │
                   │  Server     │
                   └──────┬──────┘
                     gRPC │
                   ┌──────┴──────┐
                   │  LiveKit    │
                   │  Agent      │
                   └──────┬──────┘
                          │
                  ┌───────┼───────┐
                  ▼       ▼       ▼
               [STT]   [LLM]   [TTS]
```

**Process**:
1. Frontend requests a **room token** from Core (`POST /api/livekit/token`)
2. Core generates a JWT via the LiveKit Python SDK and returns the token
3. Frontend uses the token to connect to the LiveKit Server
4. LiveKit Agent joins the room, processes audio/video through AI workflows

## 3. Event-Driven Communication (Core Internal)

Inter-module communication within the monolithic architecture uses an **Event Bus**.

For full specification, see [Event-Driven Architecture](./event-driven.md).

**Summary**:
- State changes (asynchronous) → Event Bus
- Data queries (synchronous) → Service import (in-process)
- External service calls → HTTP (httpx)

## 4. Core → Hot-Path Services: HTTP + Events

Communication between the Core Monolith and Realtime & Media services is as follows:

| Direction | Pattern | Example |
|-----------|---------|---------|
| Core → Realtime | HTTP API | Generate LiveKit room token |
| Core → Media | HTTP API | Request STT transcript |
| Realtime → Core | Redis Events | Room member joins |
| Media → Core | Redis Events | Transcript conversion complete |

```python
# Core calls Media service
import httpx

async def request_transcription(audio_url: str, user_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post("http://localhost:8831/transcribe", json={
            "audio_url": audio_url,
            "user_id": user_id,
        })
        return resp.json()
```

## 5. Database Access

All modules connect to PostgreSQL via a shared connection pool, but each module can only access its dedicated schema:

```python
# Each module uses schema-scoped queries
await cur.execute("SELECT * FROM finance.transactions WHERE user_id = %s", [user_id])
```

Driver: supports asynchronous psycopg 3.

## 6. Authentication Flow

For the complete authentication architecture, see [Auth Architecture](./auth.md).

**Summary**: Browser → signs cookie → Nginx → Core → Auth middleware validates → injects user info → module processes request. Session state stored in Redis.

## 7. Hook/Plugin Integration

Events flow through the Hook Engine, allowing plugins to intercept and extend behavior. See [Plugin System](./plugin-system.md).

## 8. Observability Integration

All communication patterns are integrated with OpenTelemetry. See [Observability](./observability.md).
```
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3166ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2951ms
