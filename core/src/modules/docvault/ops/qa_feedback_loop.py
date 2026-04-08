"""QAFeedbackLoopOp — Promote positive QA logs to FAQ cache.

Toggle: DOCVAULT_QA_FAQ_PROMOTE=1 (off by default).
Runs async fire-and-forget after feedback is recorded.

Strategy:
- FAQ pool has a size limit (DOCVAULT_FAQ_MAX_SIZE, default 200)
- When full, evicts the entry with lowest reuse_count (LRU-like)
- Duplicate promotions are idempotent (same entity_id → upsert)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

QA_FAQ_PROMOTE_ENABLED = os.environ.get("DOCVAULT_QA_FAQ_PROMOTE", "0") == "1"

PROMOTE_CONFIDENCE_THRESHOLD = 0.7
FAQ_MAX_SIZE = int(os.environ.get("DOCVAULT_FAQ_MAX_SIZE", "200"))
FAQ_SERVICE_ID = "docvault-user-faq"


async def _evict_least_used_faq() -> bool:
    """Evict the FAQ entry with the lowest reuse_count (LRU-like)."""
    try:
        from qdrant_client.http.models import (
            FieldCondition,
            Filter,
            MatchValue,
        )

        from src.shared import qdrant_client as qclient
        from src.shared.qdrant_search import COLLECTION_NAME

        client = await qclient.get_client()
        if not client:
            return False

        # Scroll all FAQ entries, find the one with lowest reuse_count
        points, _ = await client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="service_id",
                        match=MatchValue(value=FAQ_SERVICE_ID),
                    )
                ]
            ),
            limit=FAQ_MAX_SIZE + 10,
            with_payload=True,
        )

        if not points:
            return False

        # Find LRU candidate: lowest reuse_count, then oldest last_hit_at
        victim = min(
            points,
            key=lambda p: (
                p.payload.get("reuse_count", 0),
                p.payload.get("last_hit_at", 0),
            ),
        )

        await client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=[victim.id],
        )
        logger.info(
            "Evicted FAQ entry %s (reuse=%d)", victim.id, victim.payload.get("reuse_count", 0)
        )
        return True
    except Exception:
        logger.debug("FAQ eviction failed")
        return False


async def _get_faq_count() -> int:
    """Count current FAQ entries in Qdrant."""
    try:
        from qdrant_client.http.models import (
            FieldCondition,
            Filter,
            MatchValue,
        )

        from src.shared import qdrant_client as qclient
        from src.shared.qdrant_search import COLLECTION_NAME

        client = await qclient.get_client()
        if not client:
            return 0

        result = await client.count(
            collection_name=COLLECTION_NAME,
            count_filter=Filter(
                must=[
                    FieldCondition(
                        key="service_id",
                        match=MatchValue(value=FAQ_SERVICE_ID),
                    )
                ]
            ),
        )
        return result.count
    except Exception:
        return 0


class QAFeedbackLoopOp:
    """Promote high-confidence positive QA logs to the FAQ cache pool."""

    name = "QAFeedbackLoopOp"
    input_keys = ("qa_log_id", "feedback", "confidence", "query_text", "answer_text")
    output_keys = ("faq_promoted",)

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        if not QA_FAQ_PROMOTE_ENABLED:
            ctx["faq_promoted"] = False
            return ctx

        feedback = ctx.get("feedback")
        confidence = ctx.get("confidence", 0.0)
        query_text = ctx.get("query_text", "")
        answer_text = ctx.get("answer_text", "")
        qa_log_id = ctx.get("qa_log_id", "")

        if feedback != "positive" or confidence < PROMOTE_CONFIDENCE_THRESHOLD:
            ctx["faq_promoted"] = False
            return ctx

        if not query_text:
            ctx["faq_promoted"] = False
            return ctx

        try:
            from src.shared.qdrant_search import index_documents_batch

            # Check FAQ pool size limit — evict LRU if full
            current_count = await _get_faq_count()
            if current_count >= FAQ_MAX_SIZE:
                await _evict_least_used_faq()

            docs = [
                {
                    "entity_id": (
                        f"faq-{qa_log_id}" if qa_log_id else f"faq-{hash(query_text):016x}"
                    ),
                    "content": query_text,
                    "service_id": FAQ_SERVICE_ID,
                    "metadata": {
                        "answer_preview": answer_text[:200],
                        "full_answer": answer_text,
                        "confidence": confidence,
                        "source_qa_log_id": qa_log_id,
                        "reuse_count": 0,
                        "last_hit_at": time.time(),
                    },
                }
            ]
            await index_documents_batch(docs)
            ctx["faq_promoted"] = True
            logger.info(
                "Promoted FAQ (pool %d/%d): %s",
                current_count + 1,
                FAQ_MAX_SIZE,
                qa_log_id[:12] if qa_log_id else "?",
            )
        except Exception:
            logger.debug("FAQ promotion failed")
            ctx["faq_promoted"] = False

        return ctx
