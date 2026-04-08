"""QACacheLookupOp — Check pre-generated QA cache before full RAG pipeline.

Toggle: DOCVAULT_QA_CACHE=1 (off by default).
Position: Pipeline Step 0 (before IntentRouter).

Two pools:
- docvault-qa-cache (system-generated): cosine > 0.85
- docvault-user-faq (user FAQ): cosine > 0.90
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

QA_CACHE_ENABLED = os.environ.get("DOCVAULT_QA_CACHE", "0") == "1"

SYSTEM_CACHE_THRESHOLD = 0.85
FAQ_CACHE_THRESHOLD = 0.90


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
                ctx["cache_hit"] = True
                ctx["cached_answer"] = meta.get("full_answer", meta.get("answer_preview", ""))
                ctx["cache_source"] = "cached"
                ctx["cache_confidence"] = hit.get("score", 0)
                logger.info(
                    "QA cache hit (system): score=%.3f",
                    hit.get("score", 0),
                )
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
                ctx["cache_hit"] = True
                ctx["cached_answer"] = meta.get("full_answer", meta.get("answer_preview", ""))
                ctx["cache_source"] = "faq"
                ctx["cache_confidence"] = hit.get("score", 0)
                logger.info(
                    "QA cache hit (FAQ): score=%.3f",
                    hit.get("score", 0),
                )
                return ctx

        except Exception:
            logger.debug("QACacheLookupOp failed, falling through to full pipeline")

        ctx["cache_hit"] = False
        return ctx
