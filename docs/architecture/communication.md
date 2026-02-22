# Communication Patterns

## Overview

```
┌──────────────────────────────────────────────────────────┐
│  Browser (Single React App)                              │
│                                                          │
│  HTTP/SSE ──────────┐           WebRTC ──────────┐       │
└─────────────────────┼───────────────────────────┼───────┘
                      ▼                           ▼
              ┌──────────────┐           ┌──────────────┐
              │   Nginx      │           │   LiveKit     │
              │   Gateway    │           │   Server      │
              └──────┬───────┘           └──────┬───────┘
                     │                          │
                     ▼                          ▼
        ┌────────────────────────┐     ┌──────────────┐
        │    Core Monolith       │     │   Realtime    │
        │   ┌──────┬──────┐     │     │   Agents      │
        │   │auth  │quest │     │     └──────┬───────┘
        │   ├──────┼──────┤     │            │
        │   │finance│muse │     │     ┌──────┴───────┐
        │   └──────┴──────┘     │     │    Media      │
        │         │             │     │  (STT/TTS)    │
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

All frontend-to-backend communication uses **HTTP REST** via Nginx reverse proxy to the Core Monolith.

```
Browser → https://domain.com/api/finance/transactions → Nginx → Core Monolith
```

**Conventions**:
- `GET` for reads, `POST` for creates, `PUT` for full updates, `PATCH` for partial, `DELETE` for deletes
- Request/response bodies in JSON (camelCase keys for JS compatibility)
- Pagination: `?page=1&limit=20` with `X-Total-Count` header
- Errors: `{ "detail": "message" }` with appropriate HTTP status

### Streaming (SSE)

For long-running operations or LLM responses, use **Server-Sent Events**:

```
Browser → GET /api/chat/stream (Accept: text/event-stream) → Nginx → Core
         ← data: {"chunk": "Hello"}\n\n
         ← data: {"chunk": " world"}\n\n
         ← data: [DONE]\n\n
```

**When to use SSE vs WebSocket:**

| Criteria | SSE | WebSocket |
|----------|-----|-----------|
| Direction | Server → Client (unidirectional) | Bidirectional |
| Use case | LLM streaming, progress updates | Chat, real-time collaboration |
| Reconnection | Built-in auto-reconnect | Manual implementation |
| Through proxies | Works through Nginx/CDN | Needs `Upgrade` support |
| Complexity | Simple | More complex |

**Default choice: SSE** -- covers 90% of streaming needs with less complexity.

### File Upload

```
Browser → POST /api/storage/upload (multipart/form-data) → Nginx → Core → Object Store
```

## 2. Frontend ↔ LiveKit: WebRTC

For real-time voice and video, use **LiveKit** (separate Realtime service).

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

**Flow**:
1. Frontend requests a **room token** from Core (`POST /api/livekit/token`)
2. Core generates JWT via LiveKit Python SDK, returns token
3. Frontend connects to LiveKit Server with token
4. LiveKit Agent joins the room, processes audio/video with AI pipeline

## 3. Event-Driven Communication (Core Internal)

Module-to-module communication within the monolith uses the **Event Bus**.

See [Event-Driven Architecture](./event-driven.md) for full specification.

### Summary

```
State changes (async, no response needed)  → Event Bus
Data queries (sync, response needed)        → Service import (in-process)
External service calls                      → HTTP via httpx
```

### Event Flow Example

```
Finance module → publish("finance.transaction.created", {...})
    ↓
Event Bus (in-process async)
    ↓
Quest module → subscriber checks if transaction triggers achievement
Admin module → subscriber logs audit trail
Plugin hooks → any registered plugin hooks fire
```

### Rules

1. **Events for writes**: When a module changes state, it publishes an event.
2. **Service imports for reads**: When a module needs data from another module, it calls the service layer directly.
3. **Idempotent handlers**: Event subscribers must handle duplicate events gracefully.
4. **No circular dependencies**: If Module A subscribes to Module B's events and vice versa, reconsider the boundaries.

## 4. Core → Hot-Path Services: HTTP + Events

The Core Monolith communicates with Realtime and Media services through:

| Direction | Pattern | Example |
|-----------|---------|---------|
| Core → Realtime | HTTP API | Generate LiveKit room token |
| Core → Media | HTTP API | Request STT transcription |
| Realtime → Core | Redis Events | Room participant joined |
| Media → Core | Redis Events | Transcription completed |

```python
# Core calling Media service
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

All modules connect to PostgreSQL through a shared connection pool, but each module only accesses its own schema:

```python
# Each module uses schema-scoped queries
await cur.execute("SELECT * FROM finance.transactions WHERE user_id = %s", [user_id])
```

Driver: psycopg 3 with async support.

## 6. Authentication Flow

```
Browser → POST /api/auth/login (credentials) → Nginx → Core (auth module)
Auth module → Verify credentials → Create session → Set signed cookie → Redis

Browser → GET /api/finance/transactions (signed cookie) → Nginx → Core
Auth middleware → Validate cookie → Load user from Redis → Check permissions
Finance module → Process request (user injected by middleware)
```

**Rules**:
- Auth middleware runs before all protected routes (same process, no header forwarding needed)
- Session state in Redis for fast lookup and cross-instance sharing
- Never expose internal service ports to the internet

## 7. Hook/Plugin Integration

Events flow through the Hook Engine, allowing plugins to intercept and extend behavior:

```
Module publishes event
    → Event Bus delivers to module subscribers
    → Hook Engine checks for registered plugin hooks
    → Plugin hooks execute (with permission isolation)
```

See [Plugin System](./plugin-system.md) for hook specification.

## 8. Observability Integration

All communication patterns are instrumented with OpenTelemetry:

- HTTP requests: automatic span creation via FastAPI middleware
- Events: each event publish/subscribe creates a trace span
- External calls: httpx instrumentation for outbound requests
- Database: psycopg instrumentation for query tracing

See [Observability](./observability.md) for details.
