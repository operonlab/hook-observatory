"""Voice event publishing via Redis Streams."""

from __future__ import annotations

import json
import logging
import time

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class VoiceEventBus:
    """Publishes voice events to Redis Streams (ws:voice:* pattern)."""

    def __init__(self, redis: aioredis.Redis, stream_prefix: str = "ws:voice:"):
        self._redis = redis
        self._prefix = stream_prefix
        self._count = 0

    async def publish(self, event_type: str, payload: dict) -> str | None:
        """Publish an event to Redis Streams.

        Args:
            event_type: e.g. "voice.wakeword.detected"
            payload: event data dict

        Returns:
            Stream message ID, or None on failure.
        """
        stream_key = f"{self._prefix}{event_type}"
        entry = {
            "type": event_type,
            "payload": json.dumps(payload, ensure_ascii=False),
            "ts": str(time.time()),
        }
        try:
            msg_id = await self._redis.xadd(
                stream_key, entry, maxlen=200, approximate=True
            )
            self._count += 1
            logger.debug("event_published: %s → %s", event_type, msg_id)
            return msg_id
        except Exception:
            logger.exception("event_publish_failed: %s", event_type)
            return None

    @property
    def event_count(self) -> int:
        return self._count
