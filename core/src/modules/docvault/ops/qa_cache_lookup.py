"""QACacheLookupOp — Check pre-generated QA cache before full RAG pipeline.

Toggle: DOCVAULT_QA_CACHE=1 (off by default).
Position: Pipeline Step 0 (before IntentRouter).

Two pools:
- docvault-qa-cache (system-generated): cosine > 0.85
- docvault-user-faq (user FAQ): cosine > 0.90

On cache hit:
- Pre-generated QA: increment reuse_count in DB
- FAQ: increment reuse_count + refresh last_hit_at in Qdrant payload
  (extends effective TTL — frequently asked questions survive longer)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

QA_CACHE_ENABLED = os.environ.get("DOCVAULT_QA_CACHE", "0") == "1"

SYSTEM_CACHE_THRESHOLD = 0.85
FAQ_CACHE_THRESHOLD = 0.90


async def _cache_still_fresh(meta: dict[str, Any], db: Any) -> bool:
    """P2.2 invalidation: return False if the source doc was updated after cache entry.

    Compares cached `doc_updated_at` (snapshot at cache-write time) with the
    current value in PG. Legacy cache entries without `doc_updated_at` are
    treated as fresh (gracefully degrade).
    """
    cached_iso = meta.get("doc_updated_at")
    document_id = meta.get("document_id")
    if not cached_iso or not document_id or db is None:
        return True
    try:
        from datetime import datetime  # noqa: PLC0415

        from sqlalchemy import select  # noqa: PLC0415

        from src.modules.docvault.models import Document  # noqa: PLC0415

        row = (
            await db.execute(select(Document.updated_at).where(Document.id == document_id))
        ).first()
        if not row or not row[0]:
            return True
        current = row[0]
        cached = datetime.fromisoformat(cached_iso)
        # If naive vs aware mismatch, drop tz from both for comparison.
        if (cached.tzinfo is None) != (current.tzinfo is None):
            cached = cached.replace(tzinfo=None)
            current = current.replace(tzinfo=None)
        return current <= cached
    except Exception:
        logger.debug("cache freshness check failed for doc=%s", document_id)
        return True


async def _bump_preqa_reuse(entity_id: str) -> None:
    """Increment reuse_count for a pre-generated QA entry in Qdrant metadata."""
    try:
        from src.shared import qdrant_client as qclient
        from src.shared.qdrant_search import COLLECTION_NAME, _entity_to_point_id

        client = await qclient.get_client()
        if not client:
            return

        point_id = _entity_to_point_id("docvault-qa-cache", entity_id)
        points = await client.retrieve(
            collection_name=COLLECTION_NAME,
            ids=[point_id],
            with_payload=True,
        )
        if not points:
            return

        payload = points[0].payload or {}
        await client.set_payload(
            collection_name=COLLECTION_NAME,
            payload={
                "reuse_count": payload.get("reuse_count", 0) + 1,
                "last_hit_at": time.time(),
            },
            points=[point_id],
        )
    except Exception:
        logger.debug("Pre-QA reuse bump failed for %s", entity_id)


async def _bump_faq_reuse(point_id: str) -> None:
    """Increment reuse_count + refresh last_hit_at in Qdrant payload."""
    try:
        from src.shared import qdrant_client as qclient
        from src.shared.qdrant_search import COLLECTION_NAME

        client = await qclient.get_client()
        if not client:
            return

        # Read current payload
        points = await client.retrieve(
            collection_name=COLLECTION_NAME,
            ids=[point_id],
            with_payload=True,
        )
        if not points:
            return

        payload = points[0].payload or {}
        reuse_count = payload.get("reuse_count", 0) + 1

        await client.set_payload(
            collection_name=COLLECTION_NAME,
            payload={
                "reuse_count": reuse_count,
                "last_hit_at": time.time(),
            },
            points=[point_id],
        )
        logger.debug("FAQ reuse bumped: %s → %d", point_id, reuse_count)
    except Exception:
        logger.debug("FAQ reuse bump failed")


class QACacheLookupOp:
    """Check pre-computed QA cache for a semantic match."""

    name = "QACacheLookupOp"
    input_keys = ("query", "space_id")
    output_keys = ("cache_hit", "cached_answer", "cache_source", "cache_confidence")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        if not QA_CACHE_ENABLED:
            ctx["cache_hit"] = False
            return ctx

        query = ctx.get("query", "")
        if not query:
            ctx["cache_hit"] = False
            return ctx

        try:
            from src.shared.qdrant_search import hybrid_search

            # Pool 1: System-generated QA cache
            results = await hybrid_search(
                query=query,
                service_id="docvault-qa-cache",
                top_k=1,
            )
            if results and results[0].get("score", 0) >= SYSTEM_CACHE_THRESHOLD:
                hit = results[0]
                meta = hit.get("metadata", {})
                # P2.2: skip stale cache when source doc updated.
                if not await _cache_still_fresh(meta, ctx.get("db")):
                    logger.info("QA cache stale (system pool) — falling through to RAG")
                else:
                    ctx["cache_hit"] = True
                    ctx["cached_answer"] = meta.get(
                        "full_answer", meta.get("answer_preview", "")
                    )
                    ctx["cache_source"] = "cached"
                    ctx["cache_confidence"] = hit.get("score", 0)
                    logger.info(
                        "QA cache hit (system): score=%.3f",
                        hit.get("score", 0),
                    )
                    # Fire-and-forget reuse bump
                    import asyncio

                    entity_id = hit.get("entity_id", "")
                    if entity_id:
                        asyncio.get_running_loop().create_task(_bump_preqa_reuse(entity_id))
                    return ctx

            # Pool 2: User FAQ
            faq_results = await hybrid_search(
                query=query,
                service_id="docvault-user-faq",
                top_k=1,
            )
            if faq_results and faq_results[0].get("score", 0) >= FAQ_CACHE_THRESHOLD:
                hit = faq_results[0]
                meta = hit.get("metadata", {})
                # P2.2: same staleness check for user FAQ pool.
                if not await _cache_still_fresh(meta, ctx.get("db")):
                    logger.info("QA cache stale (FAQ pool) — falling through to RAG")
                    ctx["cache_hit"] = False
                    return ctx
                ctx["cache_hit"] = True
                ctx["cached_answer"] = meta.get("full_answer", meta.get("answer_preview", ""))
                ctx["cache_source"] = "faq"
                ctx["cache_confidence"] = hit.get("score", 0)
                logger.info(
                    "QA cache hit (FAQ): score=%.3f",
                    hit.get("score", 0),
                )
                # Bump reuse_count + refresh last_hit_at
                import asyncio

                point_id = hit.get("point_id", hit.get("id", ""))
                if point_id:
                    asyncio.get_running_loop().create_task(_bump_faq_reuse(point_id))
                return ctx

        except Exception:
            logger.debug("QACacheLookupOp failed, falling through to full pipeline")

        ctx["cache_hit"] = False
        return ctx
