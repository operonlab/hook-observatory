"""Memvault Reactive Adapters — native reactive via EventBus.channel().

Six concepts:
  Subject      -> EventChannel (event_bus.channel())
  Observer     -> FunctionObserver (shared/reactive.py)
  Scheduler    -> EmbeddingScheduler (semaphore-gated concurrency)
  Observable   -> EventChannel.pipe() (_PipedChannel)
  Operator     -> NoiseGateOp + TagCooccurrenceOp
  Subscription -> reactive.py Subscription (from channel.subscribe())
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from src.events.bus import EventBus, event_bus
from src.events.types import MemvaultEvents
from src.shared.database import async_session_factory
from src.shared.reactive import (
    FunctionObserver,
    Subscription,
)

from .noise_filter import check_noise

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# EmbeddingScheduler — Scheduler Protocol
# ═══════════════════════════════════════════════════════════════════════════


class EmbeddingScheduler:
    """Scheduler: semaphore-based concurrency control."""

    def __init__(self, max_concurrent: int = 5) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def schedule(self, work: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        async with self._semaphore:
            return await work(*args, **kwargs)

    async def schedule_batch(self, items: list, processor: Callable) -> list:
        async def _gated(item: Any) -> Any:
            async with self._semaphore:
                return await processor(item)

        return list(await asyncio.gather(*[_gated(item) for item in items]))


# ═══════════════════════════════════════════════════════════════════════════
# Creation Operators
# ═══════════════════════════════════════════════════════════════════════════


class NoiseGateOp:
    """Operator: content -> is_noise + noise_reason (wraps check_noise)."""

    @property
    def name(self) -> str:
        return "noise_gate"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("content",)

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("is_noise", "noise_reason")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        content = ctx.get("content", "")
        verdict = check_noise(content)
        ctx["is_noise"] = verdict.is_noise
        ctx["noise_reason"] = verdict.reason
        return ctx


class TagCooccurrenceOp:
    """Operator: tags -> triple_dicts (tag co-occurrence extraction)."""

    @property
    def name(self) -> str:
        return "tag_cooccurrence"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("tags",)

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("triple_dicts",)

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        tags = ctx.get("tags", [])
        tags = [t for t in tags if t != "_quarantine" and t.strip()]
        capped = tags[:5]

        triple_dicts = []
        for i, tag_a in enumerate(capped):
            for tag_b in capped[i + 1 :]:
                triple_dicts.append(
                    {
                        "subject": tag_a,
                        "predicate": "co_occurs_with",
                        "object": tag_b,
                    }
                )

        ctx["triple_dicts"] = triple_dicts
        return ctx


# ═══════════════════════════════════════════════════════════════════════════
# 六概念合流 Factory
# ═══════════════════════════════════════════════════════════════════════════


def wire_memory_creation_flow(
    bus: EventBus | None = None,
) -> Subscription:
    """Memory Creation Flow: channel -> pipe(operators) -> observer -> KG write.

    1. Subject      - event_bus.channel(MEMORY_STORED)
    2. Observable   - channel.pipe(NoiseGateOp, TagCooccurrenceOp)
    3. Operator     - NoiseGateOp + TagCooccurrenceOp
    4. Observer     - FunctionObserver(_kg_ingest_handler) — writes KG triples
    5. Scheduler    - EmbeddingScheduler (available for future observer use)
    6. Subscription - piped.subscribe(observer), auto-cleaned by EventBus.stop()
    """
    _bus = bus or event_bus

    # Operators
    noise_gate = NoiseGateOp()
    tag_cooccurrence = TagCooccurrenceOp()

    # Channel + pipe
    piped = _bus.channel(MemvaultEvents.MEMORY_STORED).pipe(noise_gate, tag_cooccurrence)

    # Observer — writes KG triples (moved from events.py on_memory_stored_extract_triples)
    async def _kg_ingest_handler(ctx: dict[str, Any]) -> None:
        """Process piped context: skip noise, write co-occurrence triples to KG."""
        if ctx.get("is_noise"):
            logger.debug("reactive.noise_gated", extra={"reason": ctx.get("noise_reason")})
            return

        triple_dicts = ctx.get("triple_dicts", [])
        if not triple_dicts:
            return

        space_id = ctx.get("space_id")
        if not space_id:
            return

        source_session = ctx.get("source_session") or f"block:{ctx.get('block_id', 'unknown')}"

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
                    "reactive.block_to_kg",
                    extra={
                        "block_id": ctx.get("block_id"),
                        "triples_created": result.get("ingested", 0),
                    },
                )
        except Exception:
            logger.warning(
                "reactive.block_to_kg_failed",
                extra={"block_id": ctx.get("block_id")},
                exc_info=True,
            )

    observer = FunctionObserver(_kg_ingest_handler, name="kg_triple_ingest")

    # Subscription
    return piped.subscribe(observer)
