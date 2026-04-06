"""CitedAnswerOp — generate answer with inline citations.

Default SynthSlot implementation for factual QA.
Produces an answer where every claim cites a source chunk.

Operator protocol:
  input_keys: ("question", "evidence_chunks")
  output_keys: ("answer", "citations", "confidence")
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _build_cited_answer(
    question: str,
    chunks: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], float]:
    """Build a cited answer from evidence chunks.

    Returns (answer_text, citations_list, confidence_score).
    Stub implementation — will be replaced by LLM call in Phase 2.
    """
    if not chunks:
        return "No evidence found to answer this question.", [], 0.0

    answer_parts: list[str] = [f"Based on {len(chunks)} relevant document sections:"]
    citations: list[dict[str, Any]] = []

    for i, chunk in enumerate(chunks[:6], 1):
        section = chunk.get("section_path", "Unknown section")
        page = chunk.get("page_range", "")
        page_info = f" (p.{page})" if page else ""
        excerpt = chunk.get("content", "")[:200].strip()
        answer_parts.append(f"\n[{i}] ({section}{page_info}): {excerpt}...")

        citations.append({
            "index": i,
            "document_id": chunk.get("document_id", ""),
            "chunk_id": chunk.get("id", ""),
            "section": section,
            "page": page,
            "quote": chunk.get("content", "")[:200],
        })

    answer_parts.append(
        "\n(CitedAnswerOp stub — LLM synthesis pending Phase 2)"
    )

    # Confidence based on result quality
    base_confidence = min(1.0, 0.5 + 0.1 * len(chunks))
    top_score = chunks[0].get("score", 0.5) if chunks else 0.0
    confidence = round(base_confidence * 0.6 + top_score * 0.4, 3)

    return "\n".join(answer_parts), citations, confidence


class CitedAnswerOp:
    """Default synthesis: generate answer with inline citations.

    Operator protocol:
      input_keys: ("question", "evidence_chunks")
      output_keys: ("answer", "citations", "confidence")
    """

    @property
    def name(self) -> str:
        return "cited_answer"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("question", "evidence_chunks")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("answer", "citations", "confidence")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        question: str = ctx.get("question", "")
        chunks: list[dict[str, Any]] = ctx.get("evidence_chunks", [])

        answer, citations, confidence = _build_cited_answer(question, chunks)

        ctx["answer"] = answer
        ctx["citations"] = citations
        ctx["confidence"] = confidence

        logger.info(
            "CitedAnswerOp: %d chunks → %d citations, confidence=%.2f",
            len(chunks),
            len(citations),
            confidence,
        )
        return ctx
