"""Memvault event handlers — cache invalidation + reactive pipe wiring.

KG paths (both MEMORY_STORED and capture.promoted) are handled by reactive pipes
in reactive_adapters.py, NOT by direct handlers here.
"""

import structlog

from src.events.bus import Event, event_bus
from src.events.types import (
    MemvaultEvents,
    SessionIntelligenceEvents,
)
from src.shared.cache import register_invalidation
from src.shared.database import async_session_factory

logger = structlog.get_logger()

# --- Cache invalidation wiring ---

register_invalidation(
    module="memvault",
    operations=["list_tags"],
    events=[
        MemvaultEvents.MEMORY_STORED,
        MemvaultEvents.MEMORY_UPDATED,
        MemvaultEvents.MEMORY_DELETED,
    ],
)

register_invalidation(
    module="memvault",
    operations=["profile_score"],
    events=[
        MemvaultEvents.PROFILE_UPDATED,
    ],
)


# ======================== Reactive pipes — KG enrichment ========================
# Flow 1: MEMORY_STORED → NoiseGate → TagCooccurrence → KG write
# Flow 2: capture.promoted → ConditionalOp(memvault) → BlockFetch → TagCooccurrence → KG write

from .reactive_adapters import wire_capture_promotion_flow, wire_memory_creation_flow  # noqa: E402

wire_memory_creation_flow()
wire_capture_promotion_flow()


# ======================== Intelligence → Memvault Bridge ========================


async def on_intelligence_digest_completed(event: Event) -> None:
    """Store intelligence digest as a memvault knowledge block."""
    digest_content = event.data.get("content", "")
    if not digest_content:
        return

    space_id = event.data.get("space_id", "default")
    digest_type = event.data.get("digest_type", "weekly")  # daily | weekly
    period = event.data.get("period", "")

    try:
        async with async_session_factory() as db:
            from .schemas import MemoryBlockCreate
            from .services import memory_block_service

            block_data = MemoryBlockCreate(
                content=digest_content,
                block_type="knowledge",
                tags=list(
                    dict.fromkeys(
                        ["intelligence", "digest", digest_type, *event.data.get("tags", [])]
                    )
                ),
                source_session=f"intelligence:{digest_type}:{period}",
            )
            await memory_block_service.create(db, space_id, block_data)
            await db.commit()
            logger.info(
                "flywheel.intelligence_to_memvault",
                digest_type=digest_type,
                period=period,
                space_id=space_id,
            )
    except Exception:
        logger.warning(
            "flywheel.intelligence_to_memvault_failed",
            exc_info=True,
        )


event_bus.channel(SessionIntelligenceEvents.DIGEST_COMPLETED).subscribe_handler(
    on_intelligence_digest_completed
)
