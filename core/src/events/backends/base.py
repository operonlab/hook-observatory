"""Abstract EventBackend — Strategy interface for EventBus backends."""

import contextvars
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.events.bus import Event

Handler = Callable[["Event"], Coroutine[Any, Any, None]]

# Auto-propagated correlation context — set by backends before calling handlers.
# Lives here (not in bus.py) to avoid circular imports: memory.py needs it,
# but bus.py lazy-imports memory.py.
_current_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_trace_id", default=None
)


def current_trace_id() -> str | None:
    """Return the trace_id of the event currently being dispatched, or None."""
    return _current_trace_id.get(None)


class EventBackend(ABC):
    """Abstract base for EventBus backends (in-memory, Redis Streams, etc.)."""

    @abstractmethod
    async def start(self) -> None:
        """Initialize backend resources (connections, consumer tasks, etc.)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Clean up backend resources."""
        ...

    @abstractmethod
    async def publish(self, event: "Event") -> None:
        """Publish an event to this backend."""
        ...

    @abstractmethod
    def subscribe(self, event_type: str, handler: Handler) -> None:
        """Register a handler for the given event type (or '*' for wildcard)."""
        ...

    @abstractmethod
    def use_middleware(self, middleware: Callable) -> None:
        """Register a middleware function to run before handler dispatch."""
        ...

    @property
    @abstractmethod
    def handlers(self) -> dict[str, list[Handler]]:
        """Expose the current handler registry (used for backend migration)."""
        ...
