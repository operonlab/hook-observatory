"""QAValidationOp — Validate pre-generated QA pairs using span checking.

Toggle: DOCVAULT_QA_VALIDATION=1 (off by default, follows QA_GENERATION).
Pure Python validation — no LLM calls.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

QA_VALIDATION_ENABLED = os.environ.get("DOCVAULT_QA_VALIDATION", "0") == "1"


def _validate_answer_spans(answer: str, chunks: list) -> bool:
    """Check that key content in the answer appears in source chunks."""
    if not answer or not chunks:
        return False

    answer_lower = answer.lower()
    chunk_text = " ".join(
        (c.get("content", c) if isinstance(c, dict) else str(c)).lower() for c in chunks
    )

    # Extract "important" tokens from answer (numbers, proper-noun-like words)
    import re

    numbers = re.findall(r"\d+[\d,\.]*", answer)
    numbers_fully_matched = False
    # At least half of the numbers in the answer should appear in chunks
    if numbers:
        found = sum(1 for n in numbers if n in chunk_text)
        if found < len(numbers) * 0.5:
            return False
        numbers_fully_matched = found == len(numbers)

    # Basic content overlap check
    # Relax threshold when all numbers match (paraphrased but factually correct)
    min_overlap = 0.2 if numbers_fully_matched else 0.3
    answer_words = set(answer_lower.split())
    chunk_words = set(chunk_text.split())
    if answer_words:
        overlap = len(answer_words & chunk_words) / len(answer_words)
        if overlap < min_overlap:
            return False

    return True


class QAValidationOp:
    """Validate pre-generated QA pairs against source chunks."""

    name = "QAValidationOp"
    input_keys = ("generated_qa_pairs", "chunks", "db")
    output_keys = ("validated_qa_count", "rejected_qa_count")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        if not QA_VALIDATION_ENABLED:
            ctx["validated_qa_count"] = 0
            ctx["rejected_qa_count"] = 0
            return ctx

        pairs = ctx.get("generated_qa_pairs", [])
        chunks = ctx.get("chunks", [])
        db = ctx.get("db")

        validated = 0
        rejected = 0

        from ..models import PreGeneratedQA

        for pair in pairs:
            # Get relevant chunks for this pair
            source_indices = (
                pair.source_chunk_indices if hasattr(pair, "source_chunk_indices") else []
            )
            relevant_chunks = (
                [chunks[i] for i in source_indices if i < len(chunks)]
                if source_indices
                else chunks
            )

            answer_text = pair.answer if hasattr(pair, "answer") else str(pair)
            is_valid = _validate_answer_spans(answer_text, relevant_chunks)

            # Update status in DB if we can find the record
            if db:
                from sqlalchemy import update

                question_text = pair.question if hasattr(pair, "question") else ""
                if question_text:
                    await db.execute(
                        update(PreGeneratedQA)
                        .where(
                            PreGeneratedQA.question == question_text,
                            PreGeneratedQA.status == "pending",
                        )
                        .values(
                            status="validated" if is_valid else "rejected",
                            confidence=0.8 if is_valid else 0.2,
                        )
                    )

            if is_valid:
                validated += 1
            else:
                rejected += 1

        ctx["validated_qa_count"] = validated
        ctx["rejected_qa_count"] = rejected
        logger.info("QA validation: %d validated, %d rejected", validated, rejected)
        return ctx
