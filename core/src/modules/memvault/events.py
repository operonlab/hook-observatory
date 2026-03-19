"""Memvault event handlers — cache invalidation + cross-module event bridges.

KG triple extraction from MEMORY_STORED is handled by the reactive pipe
(wire_memory_creation_flow in reactive_adapters.py), NOT by a direct handler here.
"""

import structlog

from src.events.bus import Event, event_bus
from src.events.types import (
    CaptureEvents,
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


# ======================== Reactive pipe — MEMORY_STORED → KG ========================
# The pipe (NoiseGate → TagCooccurrence → KG write) is the sole path for block→KG.

from .reactive_adapters import wire_memory_creation_flow  # noqa: E402

wire_memory_creation_flow()


# ======================== Capture Promoted → Memvault KG Enrichment ========================


async def on_capture_promoted_to_memvault(event: Event) -> None:
    """When a capture is promoted to memvault, ensure KG enrichment."""
    if event.data.get("module") != "memvault":
        return

    promoted_id = event.data.get("promoted_id")
    if not promoted_id:
        return

    try:
        async with async_session_factory() as db:
            from .services import memory_block_service

            block = await memory_block_service.get(db, promoted_id)
            if not block:
                return

            # Use TagCooccurrenceOp for co-occurrence extraction (same logic as pipe)
            from .reactive_adapters import TagCooccurrenceOp

            op = TagCooccurrenceOp()
            ctx = await op({"tags": block.tags or []})
            triple_dicts = ctx.get("triple_dicts", [])
            if not triple_dicts:
                return

            source_session = block.source_session or f"block:{block.id}"

            from .kg_schemas import TripleBatchCreate, TripleCreate
            from .kg_services import triple_service

            batch = TripleBatchCreate(
                session_id=source_session,
                triples=[TripleCreate(**t) for t in triple_dicts],
            )
            result = await triple_service.batch_ingest(db, block.space_id, batch)
            await db.commit()
            logger.info(
                "flywheel.capture_promoted_to_kg",
                capture_id=event.data.get("capture_id"),
                promoted_id=promoted_id,
                triples_created=result.get("ingested", 0),
            )
    except Exception:
        logger.warning(
            "flywheel.capture_promoted_kg_failed",
            capture_id=event.data.get("capture_id"),
            exc_info=True,
        )


event_bus.channel(CaptureEvents.PROMOTED).subscribe_handler(on_capture_promoted_to_memvault)


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
