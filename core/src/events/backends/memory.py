"""InMemoryBackend — in-process async event dispatch (extracted from bus.py)."""

from collections.abc import Callable

import structlog

from .base import EventBackend, Handler


class InMemoryBackend(EventBackend):
    """Pure in-process backend. Zero dependencies. Exact behavioral match with original bus.py."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}
        self._middleware: list[Callable] = []

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        pass  # No-op — nothing to initialise

    async def stop(self) -> None:
        pass  # No-op — nothing to tear down

    # ------------------------------------------------------------------ registration

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def use_middleware(self, middleware: Callable) -> None:
        self._middleware.append(middleware)

    @property
    def handlers(self) -> dict[str, list[Handler]]:
        return self._handlers

    # ------------------------------------------------------------------ dispatch

    async def publish(self, event) -> None:
        logger = structlog.get_logger()

        # Run middleware chain first (same order as original bus.py)
        for mw in self._middleware:
            await mw(event)

        handlers = self._handlers.get(event.type, [])
        # Dispatch to wildcard subscribers as well
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
