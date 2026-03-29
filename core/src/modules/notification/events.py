"""Notification event subscribers — map EventBus events to push notifications."""

import structlog

from src.events.bus import Event, event_bus
from src.shared.database import async_session_factory

from .schemas import PushPayload
from .services import notification_service

logger = structlog.get_logger()

# EventBus event → push notification mapping
EVENT_PUSH_MAP: dict[str, dict] = {
    "finance.budget.exceeded": {
        "category": "finance",
        "title": "預算超支警告",
        "severity": "warning",
        "tag": "finance-budget",
        "url": "/finance",
    },
    "finance.wallet.cash_gap_detected": {
        "category": "finance",
        "title": "現金錢包需要對帳",
        "severity": "warning",
        "tag": "finance-cash-gap",
        "url": "/finance",
    },
    "taskflow.task.completed": {
        "category": "taskflow",
        "title": "任務完成",
        "severity": "info",
        "tag": "taskflow-completed",
        "url": "/taskflow",
    },
    "briefing.daily.completed": {
        "category": "briefing",
        "title": "每日簡報已生成",
        "severity": "info",
        "tag": "briefing-daily",
        "url": "/briefing",
    },
}


async def on_mapped_event(event: Event) -> None:
    """Push notification for mapped EventBus events. Retries up to 3 times."""
    mapping = EVENT_PUSH_MAP.get(event.type)
    if not mapping:
        return

    body = event.data.get("message", event.data.get("detail", ""))
    payload = PushPayload(
        category=mapping["category"],
        title=mapping["title"],
        body=body,
        url=mapping.get("url", "/"),
        tag=mapping.get("tag"),
        severity=mapping.get("severity", "info"),
        user_id=event.user_id,
    )

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            async with async_session_factory() as db:
                await notification_service.send_notification(db, payload)
                await db.commit()
            return
        except Exception as e:
            logger.warning(
                "event_push_retry",
                event_type=event.type,
                attempt=attempt,
                error=str(e),
            )
            if attempt < max_retries:
                import asyncio
                await asyncio.sleep(0.5 * attempt)
    logger.error("event_push_exhausted", event_type=event.type, attempts=max_retries)


for _evt_type in EVENT_PUSH_MAP:
    event_bus.channel(_evt_type).subscribe_handler(on_mapped_event)
