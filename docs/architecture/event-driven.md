# Event-Driven Architecture

## Design Philosophy

**Everything is an event. Events drive state changes.**

When a module changes state, it publishes an event. Other modules (and plugins) subscribe to events they care about. This creates loose coupling between modules while maintaining a clear audit trail of everything that happens in the system.

```
Module A changes state
    → publishes event to Event Bus
    → Module B receives event, reacts
    → Module C receives event, reacts
    → Plugin hooks fire
    → OTel span recorded
```

## Event Structure

Every event follows this schema:

```python
@dataclass
class Event:
    type: str           # e.g., "finance.transaction.created"
    data: dict          # event payload
    id: str             # unique event ID (UUID v7)
    timestamp: str      # ISO 8601 timestamp
    source: str         # module that published the event
    user_id: str | None # user who triggered the action (if applicable)
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

| Component | Rule | Examples |
|-----------|------|---------|
| `domain` | Module name | `auth`, `finance`, `quest`, `muse` |
| `entity` | Business entity (singular) | `user`, `transaction`, `quest`, `spark` |
| `verb` | Past tense (event already happened) | `created`, `updated`, `deleted`, `completed` |

### Standard Events per Module

| Module | Events |
|--------|--------|
| auth | `auth.user.registered`, `auth.user.approved`, `auth.user.suspended`, `auth.user.logged_in`, `auth.user.logged_out` |
| finance | `finance.transaction.created`, `finance.transaction.updated`, `finance.budget.exceeded`, `finance.subscription.renewed` |
| quest | `quest.quest.created`, `quest.quest.completed`, `quest.skill.leveled_up`, `quest.reward.claimed` |
| muse | `muse.spark.created`, `muse.spark.linked`, `muse.graph.updated` |
| admin | `admin.setting.changed`, `admin.plugin.installed`, `admin.plugin.removed` |

### System Events

| Event | When |
|-------|------|
| `system.startup` | Application starts |
| `system.shutdown` | Application shutting down |
| `system.health.degraded` | Health check detects issues |

## EventBus API

### Core Interface

```python
class EventBus:
    async def publish(self, event_type: str, data: dict, **kwargs) -> str:
        """Publish an event. Returns event ID."""

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Subscribe a handler to an event type. Supports glob patterns."""

    def on(self, event_type: str) -> Callable:
        """Decorator for subscribing handlers."""

    def use(self, middleware: EventMiddleware) -> None:
        """Register middleware that runs on every event."""
```

### Publishing Events

```python
# Direct publish
event_id = await event_bus.publish(
    "finance.transaction.created",
    data={"transaction_id": "txn_abc", "amount": 150.00},
    user_id=current_user.id,
)

# Or from within a module's service layer
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

Middleware intercepts every event for cross-cutting concerns:

```python
class OTelEventMiddleware(EventMiddleware):
    """Creates OpenTelemetry spans for every event."""

    async def __call__(self, event: Event, next: Callable):
        with tracer.start_as_current_span(f"event:{event.type}") as span:
            span.set_attribute("event.id", event.id)
            span.set_attribute("event.source", event.source)
            await next(event)

class LoggingMiddleware(EventMiddleware):
    """Logs every event with structlog."""

    async def __call__(self, event: Event, next: Callable):
        log.info("event.published", event_type=event.type, event_id=event.id)
        await next(event)
        log.info("event.handled", event_type=event.type, event_id=event.id)

# Register middleware
event_bus.use(OTelEventMiddleware())
event_bus.use(LoggingMiddleware())
```

## Event Flow Examples

### 1. User Registration → Admin Notification

```
User submits registration form
    │
    ▼
Auth module: create user (status=pending)
    │
    ▼
Auth module: publish("auth.user.registered", {user_id, email, name})
    │
    ├──► Admin module subscriber: create audit log entry
    │
    ├──► Notification hook: send admin email/push notification
    │
    └──► Plugin hook (before_user_approve): custom validation
```

### 2. Transaction Created → Quest Achievement

```
User creates a financial transaction
    │
    ▼
Finance module: insert transaction, publish("finance.transaction.created", {txn_id, amount, category})
    │
    ├──► Quest module subscriber:
    │       check if user has active spending quests
    │       if threshold met → complete quest
    │       publish("quest.quest.completed", {quest_id, user_id})
    │       │
    │       ├──► Finance module subscriber: grant reward points
    │       │
    │       └──► Muse module subscriber: create achievement spark
    │
    └──► Admin module subscriber: audit log
```

### 3. Plugin Installation → Hook Registration

```
Admin installs a plugin via manifest
    │
    ▼
Admin module: validate manifest, install plugin
    │
    ▼
Admin module: publish("admin.plugin.installed", {plugin_id, hooks})
    │
    ├──► Hook Engine: register plugin's hook handlers
    │
    ├──► Auth module: register plugin's permission set
    │
    └──► Frontend: reload plugin UI slots
```

## Backend Strategy

### Phase 1: In-Process Async (Current)

Events are dispatched in-process using Python's `asyncio`:

```python
class InProcessEventBus(EventBus):
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._middleware: list[EventMiddleware] = []

    async def publish(self, event_type: str, data: dict, **kwargs) -> str:
        event = Event(type=event_type, data=data, id=str(uuid7()), ...)
        # Run through middleware chain, then dispatch to handlers
        for handler in self._match_handlers(event_type):
            asyncio.create_task(handler(event))
        return event.id
```

**Pros**: Zero latency, no external dependencies, simple debugging.
**Cons**: Events lost on process crash, no cross-process delivery.

### Phase 2: Redis Streams (Future)

When the system needs durability or cross-service events:

```python
class RedisStreamEventBus(EventBus):
    async def publish(self, event_type: str, data: dict, **kwargs) -> str:
        event = Event(type=event_type, data=data, ...)
        await self.redis.xadd(f"events:{event_type}", event.to_dict())
        return event.id
```

**Pros**: Durable, cross-service, consumer groups for load balancing.
**Cons**: Additional infrastructure, slight latency.

### Phase 3: NATS (Far Future)

If the system needs multi-node, high-throughput event streaming:
- NATS JetStream for durable streams
- Subject-based routing aligns with our naming convention
- Built-in consumer groups and replay

## Observability Integration

Every event is a first-class observability citizen:

| Signal | What | How |
|--------|------|-----|
| Trace | Each event = span in parent trace | `trace_id` field propagation |
| Metric | Event throughput, latency, error rate | OTel event middleware counters |
| Log | Structured event log | structlog with event metadata |

```python
# Automatic metrics per event type
event_counter = meter.create_counter("events.published", description="Events published")
event_latency = meter.create_histogram("events.handling_duration_ms")
```

See [Observability](./observability.md) for dashboard details.

## Rules

1. **Past tense only**: Events describe something that already happened. Never `user.create` -- always `user.created`.
2. **Events are immutable**: Once published, an event's data never changes. To correct, publish a new event.
3. **Idempotent handlers**: Subscribers must handle the same event twice without side effects.
4. **No request/response**: Events are fire-and-forget. If you need a response, use a service import.
5. **Keep payloads lean**: Include IDs and essential data. Subscribers can fetch full records via service imports.
6. **Schema evolution**: Add fields freely. Never remove or rename fields without a versioned event type.
