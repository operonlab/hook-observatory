"""Event middleware — logging."""

import structlog

logger = structlog.get_logger()


async def logging_middleware(event):
    logger.info(
        "event_published",
        event_type=event.type,
        event_id=event.id,
        source=event.source,
        user_id=event.user_id,
        trace_id=event.trace_id,
    )
