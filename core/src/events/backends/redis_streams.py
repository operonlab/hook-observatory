"""RedisStreamsBackend — persistent, at-least-once delivery via Redis Streams.

Design decisions:
- XADD for publish with maxlen backpressure
- XREADGROUP for consume (consumer group, at-least-once)
- Stream key: workshop:events:{event_type}
- Consumer group: workshop-core
- Graceful degradation: Redis down → fallback to InMemoryBackend
- Retry: 3 attempts per handler before sending to DLQ
- Dead letter stream: workshop:events:__dlq
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Callable

import structlog

from src.events.backends.base import _current_trace_id

from .base import EventBackend, Handler
from .memory import InMemoryBackend

logger = structlog.get_logger()

_STREAM_PREFIX = "workshop:events:"
_CONSUMER_GROUP = "workshop-core"
_DLQ_STREAM = "workshop:events:__dlq"
_CONSUMER_NAME = f"core-{socket.gethostname()}"
_BLOCK_MS = 2_000  # XREADGROUP block timeout
_XREAD_COUNT = 50  # max messages per XREADGROUP call


class RedisStreamsBackend(EventBackend):
    """Redis Streams backend with graceful fallback to in-memory."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        max_len: int = 10_000,
        max_retries: int = 3,
        fallback: EventBackend | None = None,
    ) -> None:
        self._redis_url = redis_url
        self._max_len = max_len
        self._max_retries = max_retries
        self._fallback: EventBackend = fallback or InMemoryBackend()
        self._handlers: dict[str, list[Handler]] = {}
        self._middleware: list[Callable] = []
        self._redis = None
        self._consumer_task: asyncio.Task | None = None
        self._degraded = False  # True when Redis is unreachable

    # ------------------------------------------------------------------ properties

    @property
    def handlers(self) -> dict[str, list[Handler]]:
        return self._handlers

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
            )
            # Probe connection
            await self._redis.ping()
            self._degraded = False
            logger.info("redis_streams_backend_connected", url=self._redis_url)
        except Exception as e:
            logger.warning(
                "redis_streams_backend_unavailable_fallback",
                error=str(e),
                fallback=type(self._fallback).__name__,
            )
            self._degraded = True

        # Start fallback backend regardless (used for degraded path or local middleware)
        await self._fallback.start()

        if not self._degraded:
            # Ensure consumer groups exist for all already-subscribed streams
            for event_type in self._handlers:
                if event_type == "*":
                    continue
                stream = _STREAM_PREFIX + event_type
                await self._ensure_group(stream)

            self._consumer_task = asyncio.create_task(
                self._consume_loop(), name="redis-streams-consumer"
            )

    async def stop(self) -> None:
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None

        await self._fallback.stop()

        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception as e:
                logger.warning("redis_streams_close_error", error=str(e))
            self._redis = None

        logger.info("redis_streams_backend_stopped")

    # ------------------------------------------------------------------ registration

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)
        # Mirror to fallback so degraded path always has handlers
        self._fallback.subscribe(event_type, handler)

    def use_middleware(self, middleware: Callable) -> None:
        self._middleware.append(middleware)
        self._fallback.use_middleware(middleware)

    # ------------------------------------------------------------------ publish

    async def publish(self, event) -> None:
        # Run middleware first (same order as original bus.py)
        for mw in self._middleware:
            await mw(event)

        if self._degraded or self._redis is None:
            # Graceful degradation: dispatch in-memory
            await self._publish_fallback(event)
            return

        try:
            stream = _STREAM_PREFIX + event.type
            payload = json.dumps(event.to_dict())
            await self._redis.xadd(
                stream,
                {"payload": payload},
                maxlen=self._max_len,
                approximate=True,
            )
        except Exception as e:
            logger.warning(
                "redis_streams_publish_failed_fallback",
                event_type=event.type,
                error=str(e),
            )
            await self._publish_fallback(event)

    async def _publish_fallback(self, event) -> None:
        """Dispatch directly in-memory (skips middleware — already run above)."""
        handlers = self._handlers.get(event.type, [])
        wildcard = self._handlers.get("*", [])
        for handler in handlers + wildcard:
            token = _current_trace_id.set(event.trace_id)
            try:
                await handler(event)
            except Exception as e:
                logger.error(
                    "event_handler_error",
                    event_type=event.type,
                    handler=handler.__name__,
                    error=str(e),
                )
            finally:
                _current_trace_id.reset(token)

    # ------------------------------------------------------------------ consumer loop

    async def _consume_loop(self) -> None:
        """Background task: XREADGROUP on all subscribed streams."""
        logger.info("redis_streams_consumer_started", consumer=_CONSUMER_NAME)
        try:
            while True:
                streams = [_STREAM_PREFIX + et for et in self._handlers if et != "*"]
                if not streams:
                    await asyncio.sleep(1)
                    continue

                try:
                    results = await self._redis.xreadgroup(
                        groupname=_CONSUMER_GROUP,
                        consumername=_CONSUMER_NAME,
                        streams={s: ">" for s in streams},
                        count=_XREAD_COUNT,
                        block=_BLOCK_MS,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("redis_streams_xreadgroup_error", error=str(e))
                    await asyncio.sleep(1)
                    continue

                if not results:
                    continue

                for stream, messages in results:
                    # stream is bytes/str like "workshop:events:finance.transaction.created"
                    event_type = stream.removeprefix(_STREAM_PREFIX)
                    for msg_id, fields in messages:
                        raw = fields.get("payload", "{}")
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            logger.warning(
                                "redis_streams_invalid_json",
                                stream=stream,
                                msg_id=msg_id,
                            )
                            await self._redis.xack(stream, _CONSUMER_GROUP, msg_id)
                            continue

                        await self._dispatch(event_type, msg_id, data, stream)

        except asyncio.CancelledError:
            logger.info("redis_streams_consumer_stopped")

    # ------------------------------------------------------------------ helpers

    async def _ensure_group(self, stream: str) -> None:
        """XGROUP CREATE if the group does not already exist."""
        try:
            await self._redis.xgroup_create(stream, _CONSUMER_GROUP, id="0", mkstream=True)
        except Exception as e:
            # BUSYGROUP = group already exists — safe to ignore
            if "BUSYGROUP" not in str(e):
                logger.warning("redis_streams_xgroup_create_error", stream=stream, error=str(e))

    async def _dispatch(
        self,
        event_type: str,
        msg_id: str,
        payload: dict,
        stream: str,
    ) -> None:
        """Dispatch to handlers with retry. On exhaustion → DLQ."""

        try:
            event = _dict_to_event(payload)
        except Exception as e:
            logger.error("redis_streams_event_deserialize_error", error=str(e), payload=payload)
            await self._redis.xack(stream, _CONSUMER_GROUP, msg_id)
            return

        handlers = self._handlers.get(event_type, [])
        wildcard = self._handlers.get("*", [])

        for handler in handlers + wildcard:
            last_error: str = ""
            succeeded = False
            token = _current_trace_id.set(event.trace_id)
            try:
                for attempt in range(1, self._max_retries + 1):
                    try:
                        await handler(event)
                        succeeded = True
                        break
                    except Exception as e:
                        last_error = str(e)
                        logger.warning(
                            "event_handler_retry",
                            event_type=event_type,
                            handler=handler.__name__,
                            attempt=attempt,
                            error=last_error,
                        )
                        if attempt < self._max_retries:
                            await asyncio.sleep(0.5 * attempt)
            finally:
                _current_trace_id.reset(token)

            if not succeeded:
                logger.error(
                    "event_handler_exhausted_sending_dlq",
                    event_type=event_type,
                    handler=handler.__name__,
                    error=last_error,
                )
                await self._send_to_dlq(payload, handler.__name__, last_error)

        # ACK after all handlers have been attempted
        try:
            await self._redis.xack(stream, _CONSUMER_GROUP, msg_id)
        except Exception as e:
            logger.warning("redis_streams_xack_error", msg_id=msg_id, error=str(e))

    async def _send_to_dlq(
        self,
        event_data: dict,
        handler_name: str,
        error: str,
    ) -> None:
        """XADD failed event to dead letter stream."""
        try:
            dlq_payload = json.dumps(
                {
                    "original_event": event_data,
                    "handler": handler_name,
                    "error": error,
                }
            )
            await self._redis.xadd(
                _DLQ_STREAM,
                {"payload": dlq_payload},
                maxlen=self._max_len,
                approximate=True,
            )
        except Exception as e:
            logger.error("redis_streams_dlq_write_error", error=str(e))
            # Last-resort fallback: persist to local file so events are not completely lost
            try:
                import datetime

                fallback_entry = json.dumps(
                    {
                        "ts": datetime.datetime.utcnow().isoformat(),
                        "original_event": event_data,
                        "handler": handler_name,
                        "error": error,
                        "dlq_error": str(e),
                    }
                )
                with open("/tmp/workshop-dlq-fallback.jsonl", "a") as f:  # noqa: ASYNC230, S108
                    f.write(fallback_entry + "\n")
            except Exception as fallback_err:
                logger.error("redis_streams_dlq_fallback_write_error", error=str(fallback_err))


# ------------------------------------------------------------------ helpers


def _dict_to_event(data: dict):
    """Reconstruct an Event from its serialised dict representation."""
    from datetime import datetime

    from src.events.bus import Event

    event = Event.__new__(Event)
    event.type = data["type"]
    event.data = data.get("data", {})
    event.id = data.get("id", "")
    event.source = data.get("source", "")
    event.user_id = data.get("user_id")
    event.trace_id = data.get("trace_id", "")
    raw_ts = data.get("timestamp", "")
    try:
        event.timestamp = datetime.fromisoformat(raw_ts)
    except (ValueError, TypeError):
        from datetime import UTC

        event.timestamp = datetime.now(UTC)
    return event
