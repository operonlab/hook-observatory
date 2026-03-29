"""In-process async event bus. Swappable to Redis Streams."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.events.backends.base import EventBackend, Handler, _current_trace_id, current_trace_id
from src.shared.reactive import Subscription

if TYPE_CHECKING:
    from src.events.channel import EventChannel

# Re-export Handler so callers can import it from here if needed
__all__ = ["Event", "EventBus", "current_trace_id", "event_bus"]

_log = logging.getLogger(__name__)


class Event:
    __slots__ = ("data", "id", "source", "timestamp", "trace_id", "type", "user_id")

    def __init__(
        self,
        type: str,
        data: dict[str, Any],
        source: str = "",
        user_id: str | None = None,
        trace_id: str | None = None,
    ):
        # SEC-07: Validate that source is consistent with the event type's module prefix.
        # Legitimate patterns:
        #   source="finance"              type="finance.transaction.created"  → exact match
        #   source="finance.cron"         type="finance.subscription.renewed" → starts with prefix
        #   source="session-intelligence" type="intelligence.digest.completed" → prefix in source
        # Any other combination may indicate spoofing — log a warning for visibility.
        if source and "." in type:
            expected_module = type.split(".")[0]
            source_lower = source.lower()
            prefix_lower = expected_module.lower()
            is_consistent = (
                source_lower == prefix_lower
                or source_lower.startswith(prefix_lower + ".")
                or prefix_lower in source_lower
            )
            if not is_consistent:
                _log.warning(
                    "Event source mismatch: source=%r but event type prefix=%r (type=%r)",
                    source,
                    expected_module,
                    type,
                )
        self.type = type
        self.data = data
        self.id = uuid.uuid4().hex
        self.timestamp = datetime.now(UTC)
        self.source = source
        self.user_id = user_id
        self.trace_id = trace_id or _current_trace_id.get(None) or uuid.uuid4().hex

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "data": self.data,
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "user_id": self.user_id,
            "trace_id": self.trace_id,
        }


class EventBus:
    """Thin facade that delegates all operations to the active EventBackend.

    Public subscription API: ``event_bus.channel(event_type)`` only.
    """

    def __init__(self, backend: EventBackend | None = None) -> None:
        if backend is None:
            from src.events.backends.memory import InMemoryBackend

            backend = InMemoryBackend()
        self._backend: EventBackend = backend
        self._channels: dict[str, EventChannel] = {}
        self._tracked_subs: list[Subscription] = []

    # ------------------------------------------------------------------ configuration

    def set_backend(self, backend: EventBackend) -> None:
        """Switch the active backend. Must be called before start()."""
        self._backend = backend

    # ------------------------------------------------------------------ channel API

    def channel(self, event_type: str) -> EventChannel:
        """Return the EventChannel for the given event type (cached)."""
        if event_type not in self._channels:
            from src.events.channel import EventChannel

            self._channels[event_type] = EventChannel(event_type, self)
        return self._channels[event_type]

    # ------------------------------------------------------------------ internal

    def _subscribe_internal(self, event_type: str, handler: Handler) -> Subscription:
        """Internal: register handler on backend and return Subscription."""
        return self._backend.subscribe(event_type, handler)

    def _track(self, sub: Subscription) -> None:
        """Track a Subscription for automatic cleanup on stop()."""
        self._tracked_subs.append(sub)

    def use(self, middleware: Callable) -> None:
        self._backend.use_middleware(middleware)

    # ------------------------------------------------------------------ dispatch

    async def publish(self, event: Event) -> None:
        try:
            await self._backend.publish(event)
        except Exception:
            _log.warning("EventBus.publish failed for %s", event.type, exc_info=True)

    async def publish_reliable(
        self, event: Event, *, max_retries: int = 3, base_delay: float = 0.5
    ) -> bool:
        """Publish with retry for critical events. Returns True on success."""
        for attempt in range(1, max_retries + 1):
            try:
                await self._backend.publish(event)
                return True
            except Exception:
                _log.warning(
                    "EventBus.publish_reliable retry %d/%d for %s",
                    attempt,
                    max_retries,
                    event.type,
                    exc_info=True,
                )
                if attempt < max_retries:
                    import asyncio

                    await asyncio.sleep(base_delay * attempt)
        _log.error("EventBus.publish_reliable exhausted for %s", event.type)
        return False

    def publish_fire_and_forget(self, event: Event) -> None:
        """Schedule event publish without awaiting. Safe for sync hooks (after_create etc.).

        NOTE: Use publish_reliable() for critical events (finance alerts, notifications).
        """
        import asyncio

        def _on_done(fut: asyncio.Future) -> None:
            if fut.exception():
                _log.warning(
                    "Fire-and-forget publish failed for %s: %s",
                    event.type,
                    fut.exception(),
                )

        task = asyncio.ensure_future(self.publish(event))
        task.add_done_callback(_on_done)

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        await self._backend.start()

    async def stop(self) -> None:
        for sub in self._tracked_subs:
            if not sub.closed:
                sub.unsubscribe()
        self._tracked_subs.clear()
        await self._backend.stop()


# Default singleton — InMemoryBackend by default, switched in lifespan if
# settings.event_backend == "redis"
event_bus = EventBus()
