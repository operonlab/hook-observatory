"""Memvault event handlers — cache invalidation + cross-module event bridges."""

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


# ======================== Shared utility ========================


def _build_cooccurrence_triples(tags: list[str], cap: int = 5) -> list[dict]:
    """Build co-occurrence triple dicts from tags, capped at `cap` tags."""
    tags = [t for t in tags if t != "_quarantine" and t.strip()]
    capped = tags[:cap]
    triples = []
    for i, tag_a in enumerate(capped):
        for tag_b in capped[i + 1 :]:
            triples.append(
                {
                    "subject": tag_a,
                    "predicate": "co_occurs_with",
                    "object": tag_b,
                }
            )
    return triples


# ======================== Gap 1: Block → KG Co-occurrence Triples ========================


async def on_memory_stored_extract_triples(event: Event) -> None:
    """Auto-extract co-occurrence KG triples from block tags."""
    tags = event.data.get("tags", [])
    triple_dicts = _build_cooccurrence_triples(tags)
    if not triple_dicts:
        return

    space_id = event.data.get("space_id")
    if not space_id:
        return

    source_session = event.data.get("source_session") or (
        f"block:{event.data.get('block_id', 'unknown')}"
    )

    try:
        async with async_session_factory() as db:
            from .kg_schemas import TripleBatchCreate, TripleCreate
            from .kg_services import triple_service

            batch = TripleBatchCreate(
                session_id=source_session,
                triples=[TripleCreate(**t) for t in triple_dicts],
            )
            result = await triple_service.batch_ingest(db, space_id, batch)
            await db.commit()
            logger.info(
                "flywheel.block_to_kg",
                block_id=event.data.get("block_id"),
                triples_created=result.get("ingested", 0),
                tags=tags[:5],
            )
    except Exception:
        logger.warning(
            "flywheel.block_to_kg_failed",
            block_id=event.data.get("block_id"),
            exc_info=True,
        )


event_bus.channel(MemvaultEvents.MEMORY_STORED).subscribe_handler(on_memory_stored_extract_triples)


# ======================== Gap 1b: Capture Promoted → Memvault Enrichment ========================


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

            triple_dicts = _build_cooccurrence_triples(block.tags or [])
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


# ======================== Gap 3: Intelligence → Memvault Bridge ========================


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


# ======================== Reactive Protocol — 六概念合流 ========================


def init_reactive_flow() -> None:
    """Initialize memvault reactive flow."""
    try:
        from .reactive_adapters import init_reactive_flow as _init

        _init()
    except Exception:
        logger.warning("memvault.reactive_flow.init_failed", exc_info=True)


def shutdown_reactive_flow() -> None:
    """Shutdown memvault reactive flow, cleanup subscriptions."""
    try:
        from .reactive_adapters import shutdown_reactive_flow as _shutdown

        _shutdown()
    except Exception:
        logger.warning("memvault.reactive_flow.shutdown_failed", exc_info=True)
