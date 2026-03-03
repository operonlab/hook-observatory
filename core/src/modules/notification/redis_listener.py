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
    """
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL)
    logger.info("redis_push_listener_started", channel=CHANNEL)

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
    except asyncio.CancelledError:
        logger.info("redis_push_listener_stopped")
    finally:
        await pubsub.unsubscribe(CHANNEL)
        await pubsub.close()
