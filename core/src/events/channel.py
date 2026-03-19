"""EventChannel — Subject + Observable bridge between EventBus and Reactive Protocol.

EventChannel is the sole subscription entry point for EventBus events.
It implements both Subject (next/error/complete) and Observable (subscribe/pipe).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.shared.reactive import (
    FunctionObserver,
    Observer,
    Operator,
    Pipeline,
    Subscription,
)

if TYPE_CHECKING:
    from src.events.bus import EventBus

logger = logging.getLogger(__name__)


class EventChannel:
    """Subject + Observable for a single event type.

    subscribe()         → full Observer
    subscribe_handler() → convenience for bare handler functions
    next()              → publish via EventBus
    pipe()              → return _PipedChannel with operators applied
    """

    def __init__(self, event_type: str, bus: EventBus) -> None:
        self._event_type = event_type
        self._bus = bus

    def subscribe(self, observer: Observer) -> Subscription:
        """Subscribe an Observer to this channel's events."""

        async def _handler(event) -> None:
            try:
                await observer.on_next(event)
            except Exception as exc:
                await observer.on_error(exc)

        sub = self._bus._subscribe_internal(self._event_type, _handler)
        self._bus._track(sub)
        return sub

    def subscribe_handler(self, handler: Callable) -> Subscription:
        """Convenience: wrap a bare handler function as FunctionObserver and subscribe."""
        observer = FunctionObserver(handler, name=getattr(handler, "__name__", "handler"))
        return self.subscribe(observer)

    async def next(self, value: dict[str, Any], *, source: str = "") -> None:
        """Subject.next — wrap value as Event and publish."""
        from src.events.bus import Event

        event = Event(type=self._event_type, data=value, source=source or "channel")
        await self._bus.publish(event)

    async def error(self, err: Exception) -> None:
        logger.exception("EventChannel[%s] error: %s", self._event_type, err)

    async def complete(self) -> None:
        pass  # no-op

    def pipe(self, *operators: Operator) -> _PipedChannel:
        """Return a new Observable with operators applied."""
        return _PipedChannel(self, operators)


class _PipedChannel:
    """Observable returned by EventChannel.pipe() — applies operators before delivery."""

    def __init__(self, source: EventChannel, operators: tuple[Operator, ...]) -> None:
        self._source = source
        self._operators = operators

    def subscribe(self, observer: Observer) -> Subscription:
        pipeline = Pipeline().pipe(*self._operators)
        piped_observer = _PipelineObserver(pipeline, observer)
        return self._source.subscribe(piped_observer)

    def pipe(self, *operators: Operator) -> _PipedChannel:
        return _PipedChannel(self._source, self._operators + operators)


class _PipelineObserver:
    """Internal Observer: event → Pipeline ctx → execute → downstream observer."""

    def __init__(self, pipeline: Pipeline, downstream: Observer) -> None:
        self._pipeline = pipeline
        self._downstream = downstream

    async def on_next(self, value: Any) -> None:
        if hasattr(value, "data"):
            ctx = dict(value.data)
        elif isinstance(value, dict):
            ctx = dict(value)
        else:
            ctx = {"value": value}
        try:
            result = await self._pipeline.execute(ctx)
            await self._downstream.on_next(result)
        except Exception as exc:
            await self._downstream.on_error(exc)

    async def on_error(self, error: Exception) -> None:
        await self._downstream.on_error(error)

    async def on_complete(self) -> None:
        await self._downstream.on_complete()
