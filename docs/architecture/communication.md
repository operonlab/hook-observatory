# Service Communication Patterns

## Overview

```
┌─────────────────────────────────────────────────────┐
│  Browser (React MFEs)                               │
│                                                     │
│  HTTP/SSE ──────────┐    WebRTC ──────────┐         │
└─────────────────────┼─────────────────────┼─────────┘
                      ▼                     ▼
              ┌──────────────┐     ┌──────────────┐
              │   Gateway    │     │   LiveKit     │
              │  (Nginx/API) │     │   Server      │
              └──────┬───────┘     └──────┬───────┘
                     │                    │
          ┌──────────┼──────────┐         │
          ▼          ▼          ▼         ▼
     ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
     │Finance │ │ Quest  │ │  Muse  │ │Agents  │
     └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘
         │          │          │          │
         └──────────┴──────────┴──────────┘
                        │
                  ┌─────┴─────┐
                  │   Redis   │ (Pub/Sub + Cache)
                  └─────┬─────┘
                        │
                  ┌─────┴─────┐
                  │ PostgreSQL│ (Per-schema)
                  └───────────┘
```

## 1. Frontend → Backend: HTTP + Streaming

### Standard Request/Response

All frontend-to-backend communication goes through **HTTP REST** via the Gateway (Nginx reverse proxy).

```
Browser → https://domain.com/api/finance/transactions → Gateway → Finance Service
```

**Conventions**:
- `GET` for reads, `POST` for creates, `PUT` for full updates, `PATCH` for partial, `DELETE` for deletes
- Request/response bodies in JSON (camelCase keys for JS compatibility)
- Pagination: `?page=1&limit=20` with `X-Total-Count` header
- Errors: `{ "detail": "message" }` with appropriate HTTP status

### Streaming (SSE)

For long-running operations or LLM responses, use **Server-Sent Events**:

```
Browser → GET /api/chat/stream (Accept: text/event-stream) → Gateway → Service
         ← data: {"chunk": "Hello"}\n\n
         ← data: {"chunk": " world"}\n\n
         ← data: [DONE]\n\n
```

**When to use SSE vs WebSocket**:

| Criteria | SSE | WebSocket |
|----------|-----|-----------|
| Direction | Server → Client (unidirectional) | Bidirectional |
| Use case | LLM streaming, progress updates | Chat, real-time collaboration |
| Reconnection | Built-in auto-reconnect | Manual implementation |
| Through proxies | Works through Nginx/CDN | Needs `Upgrade` support |
| Complexity | Simple | More complex |

**Default choice: SSE** — covers 90% of streaming needs with less complexity.

### File Upload

```
Browser → POST /api/storage/upload (multipart/form-data) → Gateway → Storage Service → Object Store
```

Large files: consider chunked upload with resumability.

## 2. Frontend ↔ LiveKit: WebRTC

For real-time voice and video, use **LiveKit** (not raw WebSocket or HTTP).

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
                   │  (Python)   │
                   └──────┬──────┘
                          │
                  ┌───────┼───────┐
                  ▼       ▼       ▼
               [STT]   [LLM]   [TTS]
```

**Flow**:
1. Frontend requests a **room token** from Gateway (`POST /api/livekit/token`)
2. Gateway generates JWT via LiveKit Python SDK, returns token
3. Frontend connects to LiveKit Server with token
4. LiveKit Agent joins the room, processes audio/video with AI pipeline

**Use cases**:
- Voice assistant conversations
- Video avatar streaming
- Screen sharing with annotation

## 3. Service ↔ Service: Redis Pub/Sub

Internal service communication uses **Redis Pub/Sub** for event-driven patterns.

### Event Format

```json
{
  "event": "transaction_created",
  "source": "finance",
  "timestamp": "2026-02-22T10:30:00Z",
  "payload": {
    "id": "txn_abc123",
    "amount": 150.00,
    "currency": "TWD"
  }
}
```

### Channel Naming Convention

```
events:<source_service>:<event_type>

Examples:
  events:finance:transaction_created
  events:quest:quest_completed
  events:gateway:user_logged_in
```

### Patterns

| Pattern | Implementation | Use Case |
|---------|---------------|----------|
| Event notification | PUBLISH + SUBSCRIBE | "Finance transaction created" → Quest checks achievements |
| Request/Reply | PUBLISH + BLPOP on reply queue | Synchronous cross-service call (avoid if possible) |
| Task queue | XADD + XREADGROUP (Streams) | Background job processing |
| Broadcast | PUBLISH to shared channel | Config reload, cache invalidation |

### Rules

1. **Fire-and-forget**: Publisher doesn't wait for subscribers. If delivery guarantee is needed, use Redis Streams instead of Pub/Sub.
2. **Idempotent handlers**: Subscribers must handle duplicate messages gracefully.
3. **No direct service calls for events**: If Service A needs to notify Service B about something, use Redis — don't make an HTTP call.
4. **HTTP for queries**: If Service A needs data from Service B, use HTTP. Redis is for events only.

```
Events (async, no response needed)  → Redis Pub/Sub
Queries (sync, response needed)     → HTTP via httpx
```

## 4. Service → Database: Direct Access

Each service connects directly to its own PostgreSQL schema. No ORM abstraction required — raw SQL with psycopg 3 is the default.

```python
import psycopg

async with await psycopg.AsyncConnection.connect(settings.db_url) as conn:
    async with conn.cursor() as cur:
        await cur.execute("SELECT * FROM finance.transactions WHERE id = %s", [txn_id])
```

## 5. Authentication Flow

```
Browser → POST /api/auth/login (credentials) → Gateway
Gateway → Verify credentials → Issue session token (cookie)
Browser → GET /api/finance/... (cookie) → Gateway
Gateway → Validate session (Redis lookup) → Forward to Finance (with X-User-Id header)
Finance → Process request (trusts X-User-Id from Gateway)
```

**Rules**:
- Only Gateway validates auth tokens
- Internal services trust Gateway's `X-User-Id` / `X-Auth-User` headers
- Never expose internal service ports to the internet
