"""In-process async event bus. Swappable to Redis Streams."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from src.events.backends.base import EventBackend, Handler

# Re-export Handler so callers can import it from here if needed
__all__ = ["Event", "EventBus", "event_bus"]


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
        self.type = type
        self.data = data
        self.id = uuid.uuid4().hex
        self.timestamp = datetime.now(UTC)
        self.source = source
        self.user_id = user_id
        self.trace_id = trace_id or uuid.uuid4().hex

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

    The public API is identical to the original in-process EventBus so all
    existing ``event_bus.on()``, ``event_bus.publish()``, and
    ``event_bus.subscribe()`` call-sites require zero changes.
    """

    def __init__(self, backend: EventBackend | None = None) -> None:
        # Lazy import to avoid circular imports at module load time
        if backend is None:
            from src.events.backends.memory import InMemoryBackend

            backend = InMemoryBackend()
        self._backend: EventBackend = backend

    # ------------------------------------------------------------------ configuration

    def set_backend(self, backend: EventBackend) -> None:
        """Switch the active backend.

        Must be called **before** ``start()``.  Any handlers already registered
        via ``subscribe()`` or ``on()`` will have been mirrored onto the new
        backend if the previous backend forwarded them (which :class:`RedisStreamsBackend`
        does automatically).  If you swap from a plain :class:`InMemoryBackend` use
        ``_copy_handlers`` to replicate existing subscriptions.
        """
        self._backend = backend

    # ------------------------------------------------------------------ registration

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._backend.subscribe(event_type, handler)

    def on(self, event_type: str):
        """Decorator: ``@event_bus.on("auth.user.registered")``"""

        def decorator(fn: Handler):
            self.subscribe(event_type, fn)
            return fn

        return decorator

    def use(self, middleware: Callable) -> None:
        self._backend.use_middleware(middleware)

    # ------------------------------------------------------------------ dispatch

    async def publish(self, event: Event) -> None:
        await self._backend.publish(event)

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        await self._backend.start()

    async def stop(self) -> None:
        await self._backend.stop()


# Default singleton — InMemoryBackend by default, switched in lifespan if
# settings.event_backend == "redis"
event_bus = EventBus()
