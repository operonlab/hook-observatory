"""Redis Pub/Sub listener — stations publish to 'workshop:push', Core delivers via Web Push."""

import asyncio
import json

import structlog

from src.shared.database import async_session_factory
from src.shared.redis import get_redis

from .schemas import PushPayload
from .services import notification_service

logger = structlog.get_logger()

CHANNEL = "workshop:push"


async def redis_push_listener() -> None:
    """Background task: subscribe to Redis 'workshop:push' and fan-out via Web Push.

    Expected message format (JSON):
    {
        "category": "sentinel",
        "title": "Service Down",
        "body": "nginx is unreachable",
        "url": "/apps/sentinel/",
        "tag": "sentinel-nginx",
        "severity": "critical",
        "user_id": null  // null = broadcast
    }

    Reconnects automatically on Redis disconnection with exponential backoff
    (max 60s). CancelledError propagates cleanly to stop the task.
    """
    attempt = 0
    while True:
        try:
            redis = get_redis()
            pubsub = redis.pubsub()
            await pubsub.subscribe(CHANNEL)
            logger.info("redis_push_listener_started", channel=CHANNEL, attempt=attempt)
            attempt = 0  # reset on successful connect

            try:
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue

                    try:
                        data = json.loads(message["data"])
                        payload = PushPayload(**data)

                        async with async_session_factory() as db:
                            await notification_service.send_notification(db, payload)
                            await db.commit()

                    except json.JSONDecodeError:
                        logger.warning("redis_push_invalid_json", data=message["data"])
                    except Exception as e:
                        logger.error("redis_push_handler_error", error=str(e))

                    # Small yield to prevent tight loop
                    await asyncio.sleep(0.01)
            finally:
                await pubsub.unsubscribe(CHANNEL)
                await pubsub.close()

        except asyncio.CancelledError:
            logger.info("redis_push_listener_stopped")
            return
        except Exception:
            attempt += 1
            wait = min(2**attempt, 60)
            logger.warning(
                "redis_push_listener_disconnected",
                reconnect_in=wait,
                attempt=attempt,
                exc_info=True,
            )
            await asyncio.sleep(wait)
