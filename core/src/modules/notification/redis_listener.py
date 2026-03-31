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

# Bounded queue — prevents unbounded memory growth under heavy load.
# At 100 pending messages the listener drops the oldest arriving message
# rather than blocking or growing without limit.
_MSG_QUEUE: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)


async def _process_queue() -> None:
    """Consumer task: drain _MSG_QUEUE and deliver each notification.

    Runs as a long-lived background task alongside the listener loop.
    Each message is processed independently; errors are logged but do not
    stop the consumer.
    """
    while True:
        data = await _MSG_QUEUE.get()
        try:
            payload = PushPayload(**data)
            async with async_session_factory() as db:
                await notification_service.send_notification(db, payload)
                await db.commit()
        except Exception as e:
            logger.warning("push_notification_handler_error", error=str(e), exc_info=True)
        finally:
            _MSG_QUEUE.task_done()


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

    Messages are placed into a bounded asyncio.Queue (maxsize=100) and
    processed by a separate consumer task to decouple ingest from delivery.
    If the queue is full, the incoming message is dropped with a warning.

    Reconnects automatically on Redis disconnection with exponential backoff
    (max 60s). CancelledError propagates cleanly to stop the task.
    """
    # Start the consumer task once, alongside this listener
    consumer_task = asyncio.ensure_future(_process_queue())

    attempt = 0
    try:
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
                        except json.JSONDecodeError:
                            logger.warning("redis_push_invalid_json", data=message["data"])
                            continue

                        try:
                            _MSG_QUEUE.put_nowait(data)
                        except asyncio.QueueFull:
                            logger.warning(
                                "push_notification_queue_full",
                                maxsize=_MSG_QUEUE.maxsize,
                                hint="dropping message",
                            )

                        # Small yield to prevent tight loop
                        await asyncio.sleep(0.01)
                finally:
                    await pubsub.unsubscribe(CHANNEL)
                    await pubsub.close()

            except asyncio.CancelledError:
                raise
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
    except asyncio.CancelledError:
        logger.info("redis_push_listener_stopped")
        consumer_task.cancel()
        raise
