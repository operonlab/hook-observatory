"""eventbus_inmem.py — Drop-in event bus adapter for memvault-os standalone deployment.

Replaces workshop's Redis Streams cross-module event bus with an in-process
asyncio.Queue-based pub/sub system.

Usage in downstream main.py:

    from adapter.eventbus_inmem import InMemEventBus, Event

    event_bus = InMemEventBus()

    # Publisher (same API as workshop event_bus)
    await event_bus.publish(Event(
        topic="memvault.block.created",
        payload={"block_id": "abc123", "space_id": "default"},
    ))

    # Subscriber (same API as workshop event_bus)
    async for event in event_bus.subscribe("memvault.block.*"):
        print(event.topic, event.payload)

Workshop compatibility surface:
- `Event` dataclass — same fields as workshop core/src/events/schemas.py
- `InMemEventBus.publish(event)` — async, fire-and-forget
- `InMemEventBus.subscribe(pattern)` — returns AsyncIterator[Event]
- Pattern matching: `*` matches one segment, `#` matches zero-or-more segments
  (follows AMQP topic exchange convention used in workshop)

Limitations:
- Restart clears all pending events (no persistence).
- No consumer groups / at-least-once delivery guarantee.
- No cross-process support (single Python process only).
- Handler exceptions are logged but do not trigger redelivery.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event model — compatible with workshop event schema surface
# ---------------------------------------------------------------------------


@dataclass
class Event:
    """An immutable event matching workshop's core event schema.

    Fields:
        topic:      Routing key in ``{module}.{entity}.{past_tense}`` format.
        payload:    Lean dict — IDs + essential data only (workshop convention).
        event_id:   Auto-generated UUID4 hex. Override for idempotency testing.
        published_at: UTC timestamp set at creation.
        source:     Optional originating service / agent identifier.
    """

    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    published_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "memvault-os"


# ---------------------------------------------------------------------------
# Pattern matching helpers
# ---------------------------------------------------------------------------


def _topic_matches(pattern: str, topic: str) -> bool:
    """Match an event topic against a subscription pattern.

    Supported wildcards (AMQP-style):
    - ``*``  matches exactly one dot-separated segment   (e.g., ``memvault.*.created``)
    - ``#``  matches zero or more dot-separated segments (e.g., ``memvault.#``)
    - Exact string match always works.

    Examples:
        ``memvault.block.*``    matches ``memvault.block.created``
                                does NOT match ``memvault.block.tag.added``
        ``memvault.#``          matches ``memvault.block.created``
                                        ``memvault.block.tag.added``
                                        ``memvault.anything``
        ``#``                   matches everything
        ``memvault.block.created`` exact match
    """
    if pattern == "#":
        return True
    if "#" not in pattern:
        # Fast path: only * wildcards — convert to fnmatch glob
        # fnmatch * matches anything including dots, so we do segment-by-segment
        p_parts = pattern.split(".")
        t_parts = topic.split(".")
        if len(p_parts) != len(t_parts):
            return False
        return all(
            p == "*" or p == t
            for p, t in zip(p_parts, t_parts)
        )
    # Contains # — convert to regex-like matching
    # Split pattern on #, each chunk is matched against consecutive segments
    p_parts = pattern.split(".")
    t_parts = topic.split(".")
    return _match_segments(p_parts, t_parts)


def _match_segments(p_parts: list[str], t_parts: list[str]) -> bool:
    """Recursive segment matcher for patterns containing #."""
    if not p_parts and not t_parts:
        return True
    if not p_parts:
        return False
    if p_parts[0] == "#":
        # # can consume 0 or more topic segments
        # Try consuming 0, 1, 2, ... segments
        for i in range(len(t_parts) + 1):
            if _match_segments(p_parts[1:], t_parts[i:]):
                return True
        return False
    if not t_parts:
        return False
    if p_parts[0] == "*" or p_parts[0] == t_parts[0]:
        return _match_segments(p_parts[1:], t_parts[1:])
    return False


# ---------------------------------------------------------------------------
# Subscriber handle
# ---------------------------------------------------------------------------


class _Subscriber:
    """Internal subscriber state — pattern + asyncio.Queue."""

    def __init__(self, pattern: str, maxsize: int = 1000) -> None:
        self.pattern = pattern
        self.queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=maxsize)
        self.id = uuid.uuid4().hex[:8]

    def matches(self, topic: str) -> bool:
        return _topic_matches(self.pattern, topic)

    def deliver(self, event: Event) -> None:
        """Non-blocking delivery — drops event if queue is full (back-pressure)."""
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(
                "InMemEventBus: subscriber %s queue full (pattern=%s), dropping event topic=%s",
                self.id,
                self.pattern,
                event.topic,
            )

    def close(self) -> None:
        """Signal the async iterator to stop by pushing a sentinel None."""
        try:
            self.queue.put_nowait(None)
        except asyncio.QueueFull:
            pass


# ---------------------------------------------------------------------------
# InMemEventBus
# ---------------------------------------------------------------------------


class InMemEventBus:
    """In-process asyncio.Queue-based event bus.

    Thread-safety: all public methods are coroutines and assume a single
    running event loop (standard asyncio pattern). Do not call from
    multiple threads without an external lock.

    Lifecycle:
        bus = InMemEventBus()
        # use in FastAPI lifespan or pass to services as dependency

        # Graceful shutdown: cancel all subscriber tasks, call close()
        await bus.close()
    """

    def __init__(self, subscriber_queue_maxsize: int = 1000) -> None:
        self._subscribers: dict[str, _Subscriber] = {}
        self._lock = asyncio.Lock()
        self._queue_maxsize = subscriber_queue_maxsize
        self._closed = False

    # ------------------------------------------------------------------
    # Core API (workshop-compatible)
    # ------------------------------------------------------------------

    async def publish(self, event: Event) -> None:
        """Publish an event to all matching subscribers.

        This is fire-and-forget: delivery to each subscriber's queue is
        attempted non-blocking. If the subscriber queue is full the event
        is dropped for that subscriber (logged as warning).

        In workshop, this method has the same async fire-and-forget contract
        (``asyncio.ensure_future`` in after_create hooks).
        """
        if self._closed:
            logger.warning("InMemEventBus: publish called on closed bus (topic=%s)", event.topic)
            return

        async with self._lock:
            matched = [
                sub for sub in self._subscribers.values()
                if sub.matches(event.topic)
            ]

        logger.debug(
            "InMemEventBus: publish topic=%s subscribers_matched=%d",
            event.topic,
            len(matched),
        )
        for sub in matched:
            sub.deliver(event)

    async def subscribe(
        self,
        pattern: str,
        *,
        timeout: float | None = None,
    ) -> AsyncIterator[Event]:
        """Subscribe to events matching ``pattern``.

        Returns an async iterator that yields matching Event objects.
        The iterator runs until the bus is closed or the caller breaks out.

        Args:
            pattern:  Routing key pattern (supports * and # wildcards).
            timeout:  Per-event wait timeout in seconds. If None, waits
                      indefinitely. Useful for test / drain scenarios.

        Example::

            async for event in bus.subscribe("memvault.block.*"):
                await handle_block_event(event)

        To unsubscribe, simply ``break`` out of the loop or let the
        coroutine return naturally.
        """
        sub = _Subscriber(pattern, maxsize=self._queue_maxsize)

        async with self._lock:
            self._subscribers[sub.id] = sub

        logger.debug(
            "InMemEventBus: new subscriber id=%s pattern=%s", sub.id, pattern
        )

        try:
            while True:
                try:
                    if timeout is not None:
                        event = await asyncio.wait_for(sub.queue.get(), timeout=timeout)
                    else:
                        event = await sub.queue.get()
                except asyncio.TimeoutError:
                    return
                except asyncio.CancelledError:
                    return

                if event is None:  # sentinel — bus closed
                    return

                yield event
        finally:
            async with self._lock:
                self._subscribers.pop(sub.id, None)
            logger.debug("InMemEventBus: subscriber id=%s unregistered", sub.id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Gracefully shut down the event bus.

        Signals all active subscribers to stop by sending a None sentinel
        to each queue.
        """
        self._closed = True
        async with self._lock:
            subs = list(self._subscribers.values())

        for sub in subs:
            sub.close()

        logger.info("InMemEventBus: closed (%d subscribers notified)", len(subs))

    @property
    def subscriber_count(self) -> int:
        """Current number of active subscribers (useful for health checks)."""
        return len(self._subscribers)


# ---------------------------------------------------------------------------
# Module-level singleton helper
# ---------------------------------------------------------------------------

_default_bus: InMemEventBus | None = None


def get_event_bus() -> InMemEventBus:
    """Return the module-level singleton InMemEventBus.

    Equivalent to workshop's ``get_event_bus()`` dependency helper.
    Create one explicitly if you need lifecycle control in FastAPI lifespan.
    """
    global _default_bus
    if _default_bus is None:
        _default_bus = InMemEventBus()
    return _default_bus
