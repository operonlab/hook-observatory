"""QAEmbedOp — Embed pre-generated questions into Qdrant for cache lookup.

Toggle: Follows DOCVAULT_QA_GENERATION.
Embeds validated QA questions into service_id="docvault-qa-cache".
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

QA_GENERATION_ENABLED = os.environ.get("DOCVAULT_QA_GENERATION", "0") == "1"


class QAEmbedOp:
    """Embed validated QA questions into Qdrant for semantic cache lookup."""

    name = "QAEmbedOp"
    input_keys = ("generated_qa_pairs", "document_id", "space_id")
    output_keys = ("qa_indexed_count",)

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        if not QA_GENERATION_ENABLED:
            ctx["qa_indexed_count"] = 0
            return ctx

        pairs = ctx.get("generated_qa_pairs", [])
        document_id = ctx.get("document_id", "")

        # Filter to validated pairs only
        validated_pairs = [
            p for p in pairs if getattr(p, "answer", None)
        ]

        if not validated_pairs:
            ctx["qa_indexed_count"] = 0
            return ctx

        try:
            from src.shared.qdrant_search import index_documents_batch

            docs = []
            for i, pair in enumerate(validated_pairs):
                question = pair.question if hasattr(pair, "question") else str(pair)
                answer = pair.answer if hasattr(pair, "answer") else ""
                docs.append(
                    {
                        "entity_id": f"qa-{document_id[:12]}-{i:03d}",
                        "content": question,
                        "service_id": "docvault-qa-cache",
                        "metadata": {
                            "document_id": document_id,
                            "answer_preview": answer[:200],
                            "question_type": getattr(pair, "question_type", "factual"),
                            "full_answer": answer,
                        },
                    }
                )

            indexed = await index_documents_batch(docs)
            ctx["qa_indexed_count"] = indexed
            logger.info(
                "Indexed %d QA questions for document %s",
                indexed,
                document_id[:12],
            )
        except Exception:
            logger.exception("QAEmbedOp failed")
            ctx["qa_indexed_count"] = 0

        return ctx
