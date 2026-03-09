"""Briefing SSE streaming — Redis PubSub publisher and SSE generator.

Architecture:
  BriefingStreamPublisher  →  Redis PubSub channel  →  briefing_stream_generator
  (called by background AI tasks)    (per briefing_id)   (subscribed by SSE endpoint)

Channel naming: briefing:stream:{briefing_id}
"""

import asyncio
import json
from collections.abc import AsyncIterator

import structlog

from src.shared.redis import get_redis
from src.shared.sse import BlockType, StreamBlock, format_sse

logger = structlog.get_logger()

_CHANNEL_PREFIX = "briefing:stream"
_DEFAULT_TIMEOUT = 300.0  # 5 minutes


def _channel(briefing_id: str) -> str:
    return f"{_CHANNEL_PREFIX}:{briefing_id}"


class BriefingStreamPublisher:
    """Publish streaming blocks to Redis PubSub for SSE delivery."""

    def __init__(self, briefing_id: str) -> None:
        self.briefing_id = briefing_id
        self.channel = _channel(briefing_id)
        self._redis = get_redis()

    async def publish(self, block: StreamBlock) -> None:
        """Publish a StreamBlock as JSON to the PubSub channel."""
        try:
            payload = block.model_dump_json()
            await self._redis.publish(self.channel, payload)
        except Exception:
            logger.exception(
                "briefing_stream_publish_error",
                channel=self.channel,
                block_type=block.type,
            )

    async def progress(self, phase: str, progress: float, message: str = "") -> None:
        """Convenience: publish a progress block."""
        await self.publish(
            StreamBlock(
                type=BlockType.PROGRESS,
                data={"phase": phase, "progress": progress, "message": message},
            )
        )

    async def content(self, phase: str, text: str, is_delta: bool = True) -> None:
        """Convenience: publish a content block."""
        await self.publish(
            StreamBlock(
                type=BlockType.CONTENT,
                data={"phase": phase, "text": text, "is_delta": is_delta},
            )
        )

    async def thinking(self, text: str) -> None:
        """Convenience: publish a thinking block."""
        await self.publish(
            StreamBlock(
                type=BlockType.THINKING,
                data={"text": text},
            )
        )

    async def done(self, entry_id: str | None = None) -> None:
        """Publish done block to terminate the stream."""
        await self.publish(
            StreamBlock(
                type=BlockType.DONE,
                data={"entry_id": entry_id} if entry_id else {},
            )
        )

    async def error(self, message: str, code: str = "unknown") -> None:
        """Publish error block."""
        await self.publish(
            StreamBlock(
                type=BlockType.ERROR,
                data={"message": message, "code": code},
            )
        )

    async def close(self) -> None:
        """Close the underlying Redis client."""
        try:
            await self._redis.aclose()
        except Exception:
            logger.debug("briefing_stream_redis_close_error", exc_info=True)


async def briefing_stream_generator(
    briefing_id: str,
    *,
    stream_timeout: float = _DEFAULT_TIMEOUT,
) -> AsyncIterator[dict]:
    """Async generator yielding SSE events from Redis PubSub.

    Subscribes to ``briefing:stream:{briefing_id}`` channel.
    Yields dicts compatible with sse-starlette's EventSourceResponse.
    Terminates on DONE block or after ``timeout`` seconds of inactivity.
    """
    redis = get_redis()
    pubsub = redis.pubsub()
    channel = _channel(briefing_id)
    await pubsub.subscribe(channel)
    logger.info("briefing_stream_subscribed", briefing_id=briefing_id, channel=channel)

    try:
        deadline = asyncio.get_event_loop().time() + stream_timeout

        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.warning(
                    "briefing_stream_timeout",
                    briefing_id=briefing_id,
                    timeout=stream_timeout,
                )
                break

            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                    timeout=min(remaining, 5.0),
                )
            except TimeoutError:
                continue

            if message is None:
                await asyncio.sleep(0.05)
                continue

            if message.get("type") != "message":
                continue

            raw = message.get("data", "")
            try:
                block_data = json.loads(raw)
                block = StreamBlock.model_validate(block_data)
            except Exception:
                logger.warning(
                    "briefing_stream_invalid_block",
                    briefing_id=briefing_id,
                    raw=raw[:200],
                )
                continue

            # Reset inactivity deadline on any valid block
            deadline = asyncio.get_event_loop().time() + stream_timeout

            yield format_sse(block)

            if block.type == BlockType.DONE:
                logger.info("briefing_stream_done", briefing_id=briefing_id)
                break

    except asyncio.CancelledError:
        logger.info("briefing_stream_cancelled", briefing_id=briefing_id)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await redis.aclose()
        logger.info("briefing_stream_closed", briefing_id=briefing_id)
