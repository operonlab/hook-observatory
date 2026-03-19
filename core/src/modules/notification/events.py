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
    """Push notification for mapped EventBus events."""
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

    try:
        async with async_session_factory() as db:
            await notification_service.send_notification(db, payload)
            await db.commit()
    except Exception as e:
        logger.error("event_push_failed", event_type=event.type, error=str(e))


for _evt_type in EVENT_PUSH_MAP:
    event_bus.channel(_evt_type).subscribe_handler(on_mapped_event)
