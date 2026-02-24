---
doc_version: 1
content_hash: 3ff968ae
source_version: 1
target_lang: en
translated_at: 2026-02-24
source_hash: 2b5a3cb3
source_lang: zh-TW
---

# Event-Driven Architecture

## Design Philosophy

**Everything is an event. Events drive state changes.**

When a module changes state, it publishes an event. Other modules (and plugins) subscribe to the events they care about. This creates loose coupling between modules while maintaining a clear audit trail of everything that happens in the system.

```
Module A changes state
    → Publishes event to Event Bus
    → Module B receives the event and reacts
    → Module C receives the event and reacts
    → Plugin Hook triggers
    → Records OTel span
```

## Event Structure

Every event follows the following schema:

```python
 @.cache/uv/archive-v0/uj_7CuQMD1gog0o_f4ybB/huggingface_hub/dataclasses.py
class Event:
    type: str           # e.g., "finance.transaction.created"
    data: dict          # Event payload
    id: str             # Unique event ID (UUID v7)
    timestamp: str      # ISO 8601 timestamp
    source: str         # The module that published the event
    user_id: str | None # The user who triggered the action (if applicable)
    trace_id: str       # OpenTelemetry trace ID for correlation
```

Example:

```json
{
  "type": "finance.transaction.created",
  "data": {
    "transaction_id": "txn_abc123",
    "amount": 150.00,
    "currency": "TWD",
    "category": "food"
  },
  "id": "evt_01HQXYZ...",
  "timestamp": "2026-02-22T10:30:00Z",
  "source": "finance",
  "user_id": "usr_456",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"
}
```

## Event Naming Convention

```
{domain}.{entity}.{past_tense_verb}
```

| Component | Rule | Example |
|-----------|------|---------|
| `domain` | Module name | `auth`, `finance`, `quest`, `muse` |
| `entity` | Business entity (singular) | `user`, `transaction`, `quest`, `spark` |
| `verb` | Past tense (the event has already occurred) | `created`, `updated`, `deleted`, `completed` |

### Standard Events by Module

| Module | Event |
|--------|--------|
| auth | `auth.user.registered`, `auth.user.approved`, `auth.user.suspended`, `auth.user.logged_in`, `auth.user.logged_out` |
| finance | `finance.transaction.created`, `finance.transaction.updated`, `finance.budget.exceeded`, `finance.subscription.renewed` |
| quest | `quest.quest.created`, `quest.quest.completed`, `quest.skill.leveled_up`, `quest.reward.claimed` |
| muse | `muse.spark.created`, `muse.spark.linked`, `muse.graph.updated` |
| admin | `admin.setting.changed`, `admin.plugin.installed`, `admin.plugin.removed` |

### System Events

| Event | When Triggered |
|-------|------|
| `system.startup` | Application startup |
| `system.shutdown` | Application is shutting down |
| `system.health.degraded` | Health check detects an issue |

## EventBus API

### Core Interface

```python
class EventBus:
    async def publish(self, event_type: str, data: dict, **kwargs) -> str:
        """Publish an event. Returns the event ID."""

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Subscribe a handler to a specific event type. Supports glob patterns."""

    def on(self, event_type: str) -> Callable:
        """Decorator for subscribing handlers."""

    def use(self, middleware: EventMiddleware) -> None:
        """Register middleware that runs on every event."""
```

### Publishing Events

```python
# Direct publishing
event_id = await event_bus.publish(
    "finance.transaction.created",
    data={"transaction_id": "txn_abc", "amount": 150.00},
    user_id=current_user.id,
)

# Or publishing from within a module's service layer
class TransactionService:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

    async def create_transaction(self, data: CreateTransactionRequest, user_id: str):
        txn = await self.repo.insert(data)
        await self.event_bus.publish(
            "finance.transaction.created",
            data={"transaction_id": str(txn.id), "amount": txn.amount},
            user_id=user_id,
        )
        return txn
```

### Subscribing to Events

```python
# Decorator style
 @event_bus.on("finance.transaction.created")
async def on_transaction_created(event: Event):
    # Check if this triggers a quest achievement
    await check_spending_quest(event.data["transaction_id"], event.user_id)

# Glob pattern subscription
 @event_bus.on("finance.*.*")
async def on_any_finance_event(event: Event):
    # Audit log all finance events
    await audit_log.record(event)

# Manual subscription
event_bus.subscribe("quest.quest.completed", handle_quest_completion)
```

### Middleware

Middleware intercepts every event to handle cross-cutting concerns:

```python
class OTelEventMiddleware(EventMiddleware):
    """Create OpenTelemetry spans for each event."""

    async def __call__(self, event: Event, next: Callable):
        with tracer.start_as_current_span(f"event:{event.type}") as span:
            span.set_attribute("event.id", event.id)
            span.set_attribute("event.source", event.source)
            await next(event)

class LoggingMiddleware(EventMiddleware):
    """Log every event using structlog."""

    async def __call__(self, event: Event, next: Callable):
        log.info("event.published", event_type=event.type, event_id=event.id)
        await next(event)
        log.info("event.handled", event_type=event.type, event_id=event.id)

# Register middleware
event_bus.use(OTelEventMiddleware())
event_bus.use(LoggingMiddleware())
```

## Example Event Flows

### 1. User Registration → Admin Notification

```
User submits registration form
    │
    ▼
Auth Module: Creates user (status=pending)
    │
    ▼
Auth Module: publishes("auth.user.registered", {user_id, email, name})
    │
    ├──► Admin Module Subscriber: Creates audit log entry
    │
    ├──► Notification Hook: Sends admin email/push notification
    │
    └──► Plugin Hook (before_user_approve): Custom validation
```

### 2. Transaction Creation → Quest Achievement

```
User creates a financial transaction
    │
    ▼
Finance Module: Inserts transaction, publishes("finance.transaction.created", {txn_id, amount, category})
    │
    ├──► Quest Module Subscriber:
    │       Checks if user has an active spending quest
    │       If threshold is met → complete quest
    │       publishes("quest.quest.completed", {quest_id, user_id})
    │       │
    │       ├──► Finance Module Subscriber: Issues reward points
    │       │
    │       └──► Muse Module Subscriber: Creates achievement spark
    │
    └──► Admin Module Subscriber: Audit log
```

### 3. Plugin Installation → Hook Registration

```
Admin installs plugin via Manifest
    │
    ▼
Admin Module: Validates Manifest, installs plugin
    │
    ▼
Admin Module: publishes("admin.plugin.installed", {plugin_id, hooks})
    │
    ├──► Hook Engine: Registers plugin's Hook handlers
    │
    ├──► Auth Module: Registers plugin's permission sets
    │
    └──► Frontend: Reloads plugin UI slots
```

## Backend Strategy

### Stage 1: In-Process Async (Current)

Events are dispatched in-process using Python's `asyncio`:

```python
class InProcessEventBus(EventBus):
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._middleware: list[EventMiddleware] = []

    async def publish(self, event_type: str, data: dict, **kwargs) -> str:
        event = Event(type=event_type, data=data, id=str(uuid7()), ...)
        # Run through the middleware chain, then dispatch to handlers
        for handler in self._match_handlers(event_type):
            asyncio.create_task(handler(event))
        return event.id
```

**Pros**: Zero latency, no external dependencies, simple debugging.
**Cons**: Events are lost on process crash, no cross-process delivery.

### Stage 2: Redis Streams (Future)

When the system requires persistence or cross-service events:

```python
class RedisStreamEventBus(EventBus):
    async def publish(self, event_type: str, data: dict, **kwargs) -> str:
        event = Event(type=event_type, data=data, ...)
        await self.redis.xadd(f"events:{event_type}", event.to_dict())
        return event.id
```

**Pros**: Persistence, cross-service, supports consumer groups for load balancing.
**Cons**: Additional infrastructure, minor latency.

### Stage 3: NATS (Distant Future)

If the system requires multi-node, high-throughput event streaming:
- Use NATS JetStream for persistent streams
- Subject-based routing aligns with our naming convention
- Built-in consumer groups and replay functionality

## Observability Integration

Every event is a first-class observability citizen:

| Signal | Content | How |
|--------|------|-----|
| Trace | Each event = one Span in a parent Trace | `trace_id` field is passed |
| Metric | Event throughput, latency, error rate | OTel event middleware counters |
| Log | Structured event logs | structlog with event metadata |

```python
# Automatic metrics for each event type
event_counter = meter.create_counter("events.published", description="Number of events published")
event_latency = meter.create_histogram("events.handling_duration_ms")
```

For dashboard details, see [Observability](./observability.md).

## Rules

1. **Past Tense Only**: Events describe something that has already happened. Never use `user.create` — always use `user.created`.
2. **Events are Immutable**: Once published, an event's data never changes. To make a correction, publish a new event.
3. **Idempotent Handlers**: Subscribers must be able to process the same event twice without side effects.
4. **No Request/Response**: Events are fire-and-forget. If you need a response, use a service import.
5. **Keep Payloads Lean**: Include only IDs and essential data. Subscribers can fetch the full record via service imports.
6. **Schema Evolution**: Feel free to add fields. Never remove or rename fields without versioning the event type.
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2454ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2711ms
