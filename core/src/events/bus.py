"""In-process async event bus. Swappable to Redis Streams."""

import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

import structlog

Handler = Callable[["Event"], Coroutine[Any, Any, None]]


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
    def __init__(self):
        self._handlers: dict[str, list[Handler]] = {}
        self._middleware: list[Callable] = []
        self._running = False

    def subscribe(self, event_type: str, handler: Handler):
        self._handlers.setdefault(event_type, []).append(handler)

    def on(self, event_type: str):
        """Decorator: @event_bus.on("auth.user.registered")"""

        def decorator(fn: Handler):
            self.subscribe(event_type, fn)
            return fn

        return decorator

    async def publish(self, event: Event):
        logger = structlog.get_logger()
        for mw in self._middleware:
            await mw(event)
        handlers = self._handlers.get(event.type, [])
        # Also dispatch to wildcard subscribers
        wildcard = self._handlers.get("*", [])
        for handler in handlers + wildcard:
            try:
                await handler(event)
            except Exception as e:
                logger.error(
                    "event_handler_error",
                    event_type=event.type,
                    handler=handler.__name__,
                    error=str(e),
                )

    def use(self, middleware: Callable):
        self._middleware.append(middleware)

    async def start(self):
        self._running = True

    async def stop(self):
        self._running = False


event_bus = EventBus()
