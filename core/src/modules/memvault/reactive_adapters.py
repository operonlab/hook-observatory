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


_active_subscription: Subscription | None = None


def wire_memory_creation_flow(
    bus: EventBus | None = None,
    max_concurrent: int = 3,
) -> Subscription:
    """Memory Creation Flow: channel -> pipe(operators) -> observer.

    1. Subject      - event_bus.channel(MEMORY_STORED)
    2. Observable   - channel.pipe(NoiseGateOp, TagCooccurrenceOp)
    3. Operator     - NoiseGateOp + TagCooccurrenceOp
    4. Observer     - FunctionObserver(kg_triple_log_handler)
    5. Scheduler    - EmbeddingScheduler(max_concurrent)
    6. Subscription - piped.subscribe(observer), unsubscribe on shutdown
    """
    _bus = bus or event_bus

    # Operators
    noise_gate = NoiseGateOp()
    tag_cooccurrence = TagCooccurrenceOp()

    # Channel + pipe
    piped = _bus.channel(MemvaultEvents.MEMORY_STORED).pipe(noise_gate, tag_cooccurrence)

    # Scheduler (available for future use by observer internals)
    EmbeddingScheduler(max_concurrent)  # reserved for future observer use

    # Observer
    async def _kg_ingest_handler(ctx: dict[str, Any]) -> None:
        """Process piped context: skip noise, log triples."""
        if ctx.get("is_noise"):
            logger.debug("reactive.noise_gated", extra={"reason": ctx.get("noise_reason")})
            return

        triple_dicts = ctx.get("triple_dicts", [])
        if not triple_dicts:
            return

        for triple in triple_dicts:
            logger.info("reactive.triple_extracted", extra={"triple": triple})

    observer = FunctionObserver(_kg_ingest_handler, name="kg_triple_ingest")

    # Subscription
    return piped.subscribe(observer)


def init_reactive_flow() -> None:
    """Initialize reactive flow (called by events.py)."""
    global _active_subscription
    if _active_subscription is not None:
        return
    _active_subscription = wire_memory_creation_flow()
    logger.info("memvault.reactive_flow.initialized")


def shutdown_reactive_flow() -> None:
    """Shutdown reactive flow (called by events.py)."""
    global _active_subscription
    if _active_subscription is not None:
        _active_subscription.unsubscribe()
        _active_subscription = None
        logger.info("memvault.reactive_flow.shutdown")
