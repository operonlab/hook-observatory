"""Capture event handlers — auto-enrichment on create via Haiku."""

import asyncio
import logging

from src.events.bus import Event, event_bus
from src.events.types import CaptureEvents
from src.shared.database import async_session_factory

logger = logging.getLogger(__name__)


@event_bus.on(CaptureEvents.CREATED)
async def on_capture_created_auto_enrich(event: Event) -> None:
    """Auto-enrich new captures via LLM when raw_input is present.

    Spawns a background task to avoid blocking the create() transaction.
    The create route commits AFTER this handler returns, so we need a
    short delay before reading the capture from a separate DB session.
    """
    data = event.data
    raw_input = data.get("raw_input")
    completeness = data.get("completeness", 0.0)
    capture_id = data.get("capture_id")

    if not capture_id or not raw_input or completeness >= 0.8:
        return

    module = data.get("module", "")
    entity_type = data.get("entity_type", "")

    # Schedule as background task — lets create() commit first
    asyncio.create_task(_do_auto_enrich(capture_id, module, entity_type, raw_input))


async def _do_auto_enrich(capture_id: str, module: str, entity_type: str, raw_input: str) -> None:
    """Background: wait for commit, then run enrichment pipeline."""
    # Brief delay to let the create route commit the transaction
    await asyncio.sleep(1.5)

    try:
        async with async_session_factory() as db:
            from .registry import get_adapter
            from .schemas import CaptureUpdate
            from .services import capture_service
            from .strategies import DefaultsStrategy, EnrichmentPipeline

            capture = await capture_service.get(db, capture_id)
            if not capture or capture.status != "pending":
                return

            adapter = get_adapter(module, entity_type)
            if not adapter:
                return

            adapter_strategies = getattr(adapter, "enrichment_strategies", None)
            if not adapter_strategies:
                return

            # Build pipeline: Defaults → adapter strategies (includes LLM)
            pipeline = EnrichmentPipeline()
            pipeline.add(
                DefaultsStrategy(
                    adapter_defaults=adapter.default_values,
                )
            )
            for strategy in adapter_strategies:
                pipeline.add(strategy)

            result = await pipeline.run(
                capture.payload,
                module=module,
                entity_type=entity_type,
                context={"raw_input": raw_input},
            )

            # Only update if pipeline produced new fields
            new_fields = {
                k: v for k, v in result.payload.items() if v and capture.payload.get(k) != v
            }
            if not new_fields:
                return

            await capture_service.update(
                db,
                capture_id,
                CaptureUpdate(payload=new_fields),
                agent_id="auto_haiku",
            )
            await db.commit()

            logger.info(
                "capture.auto_enrich: id=%s module=%s fields=%s confidence=%.2f",
                capture_id,
                module,
                list(new_fields.keys()),
                result.confidence,
            )
    except Exception:
        logger.warning(
            "capture.auto_enrich failed: id=%s",
            capture_id,
            exc_info=True,
        )
