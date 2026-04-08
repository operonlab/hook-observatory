"""QAFeedbackLoopOp — Promote positive QA logs to FAQ cache.

Toggle: DOCVAULT_QA_FAQ_PROMOTE=1 (off by default).
Runs async fire-and-forget after feedback is recorded.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

QA_FAQ_PROMOTE_ENABLED = os.environ.get("DOCVAULT_QA_FAQ_PROMOTE", "0") == "1"

PROMOTE_CONFIDENCE_THRESHOLD = 0.7


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

            docs = [
                {
                    "entity_id": (
                        f"faq-{qa_log_id}" if qa_log_id else f"faq-{hash(query_text):016x}"
                    ),
                    "content": query_text,
                    "service_id": "docvault-user-faq",
                    "metadata": {
                        "answer_preview": answer_text[:200],
                        "full_answer": answer_text,
                        "confidence": confidence,
                        "source_qa_log_id": qa_log_id,
                    },
                }
            ]
            await index_documents_batch(docs)
            ctx["faq_promoted"] = True
            logger.info("Promoted QA log %s to FAQ pool", qa_log_id[:12] if qa_log_id else "?")
        except Exception:
            logger.debug("FAQ promotion failed")
            ctx["faq_promoted"] = False

        return ctx
