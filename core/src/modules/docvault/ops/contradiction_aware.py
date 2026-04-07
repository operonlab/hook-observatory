"""ContradictionAwareOp — contradiction-detecting synthesis for legal domains.

SynthSlot implementation: question + evidence_chunks → answer with contradiction analysis.
When multiple sources provide conflicting information, this Op explicitly
surfaces the contradictions rather than silently picking one.

Design principles:
  - Legal/regulatory contexts require awareness of conflicting provisions
  - Newer documents generally supersede older ones (lex posterior)
  - More specific provisions override general ones (lex specialis)
  - Contradictions are surfaced, not hidden — the user decides
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from text_ops.overlap import jaccard_word_overlap as _compute_text_overlap

logger = logging.getLogger(__name__)


@dataclass
class Contradiction:
    """A detected contradiction between two document chunks."""

    chunk_a_id: str
    chunk_b_id: str
    chunk_a_section: str
    chunk_b_section: str
    chunk_a_excerpt: str
    chunk_b_excerpt: str
    contradiction_type: str  # direct | temporal | scope
    resolution_hint: str | None = None


def _detect_contradictions(
    chunks: list[dict[str, Any]],
    overlap_threshold: float = 0.3,
) -> list[Contradiction]:
    """Detect potential contradictions among top-k chunks.

    Heuristic: high topic overlap (shared words) but different assertions
    suggest potential contradiction. This is a lightweight pre-filter;
    LLM-based validation will be added in Phase 2.
    """
    contradictions: list[Contradiction] = []

    for i, chunk_a in enumerate(chunks):
        for chunk_b in chunks[i + 1 :]:
            content_a = chunk_a.get("content", "")
            content_b = chunk_b.get("content", "")

            overlap = _compute_text_overlap(content_a, content_b)

            if overlap < overlap_threshold:
                continue  # different topics, not a contradiction

            # High overlap but different documents → potential contradiction
            doc_a = chunk_a.get("document_id", "")
            doc_b = chunk_b.get("document_id", "")
            if doc_a == doc_b:
                continue  # same document, likely just related sections

            # Determine contradiction type
            created_a = chunk_a.get("created_at")
            created_b = chunk_b.get("created_at")
            if created_a and created_b and created_a != created_b:
                c_type = "temporal"
                newer = "A" if str(created_a) > str(created_b) else "B"
                hint = f"Chunk {newer} is newer (lex posterior may apply)"
            else:
                c_type = "direct"
                hint = "Review both provisions; consider scope and specificity"

            contradictions.append(
                Contradiction(
                    chunk_a_id=chunk_a.get("id", f"chunk_{i}"),
                    chunk_b_id=chunk_b.get("id", f"chunk_{i + 1}"),
                    chunk_a_section=chunk_a.get("section_path", "Unknown"),
                    chunk_b_section=chunk_b.get("section_path", "Unknown"),
                    chunk_a_excerpt=content_a[:200],
                    chunk_b_excerpt=content_b[:200],
                    contradiction_type=c_type,
                    resolution_hint=hint,
                )
            )

    return contradictions


def _format_contradiction_summary(contradictions: list[Contradiction]) -> str:
    """Format contradictions into a human-readable summary."""
    if not contradictions:
        return ""

    parts = ["\n⚠️ **Contradictions Detected:**\n"]
    for i, c in enumerate(contradictions, 1):
        parts.append(
            f"{i}. **{c.contradiction_type.title()} conflict**\n"
            f"   - Source A ({c.chunk_a_section}): {c.chunk_a_excerpt[:100]}...\n"
            f"   - Source B ({c.chunk_b_section}): {c.chunk_b_excerpt[:100]}...\n"
            f"   - Resolution hint: {c.resolution_hint or 'Manual review required'}\n"
        )
    return "\n".join(parts)


class ContradictionAwareOp:
    """SynthSlot Op: contradiction-aware synthesis for legal domains.

    Implements the Operator protocol:
      - input_keys: ("question", "evidence_chunks")
      - output_keys: ("answer", "citations", "contradictions", "confidence")

    Extends basic citation synthesis with explicit contradiction detection.
    When conflicting provisions are found, the answer presents both sides
    with guidance on which might take precedence.
    """

    def __init__(self, overlap_threshold: float = 0.3) -> None:
        self._overlap_threshold = overlap_threshold

    @property
    def name(self) -> str:
        return "contradiction_aware"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("question", "evidence_chunks")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("answer", "citations", "contradictions", "confidence")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        question: str = ctx.get("question", "")  # noqa: F841 — used in Phase 2 LLM synthesis
        chunks: list[dict[str, Any]] = ctx.get("evidence_chunks", [])

        if not chunks:
            ctx["answer"] = "No evidence found to answer this question."
            ctx["citations"] = []
            ctx["contradictions"] = []
            ctx["confidence"] = 0.0
            return ctx

        # Detect contradictions
        contradictions = _detect_contradictions(chunks, self._overlap_threshold)

        # Build answer with contradiction awareness
        answer_parts: list[str] = []

        # Main answer from evidence
        answer_parts.append(f"Based on {len(chunks)} relevant document sections:")
        for i, chunk in enumerate(chunks[:5], 1):
            section = chunk.get("section_path", "Unknown")
            excerpt = chunk.get("content", "")[:150].strip()
            answer_parts.append(f"\n[{i}] ({section}): {excerpt}...")

        # Append contradiction summary
        if contradictions:
            answer_parts.append(_format_contradiction_summary(contradictions))

        answer_parts.append("\n(ContradictionAwareOp stub — LLM synthesis pending Phase 1)")

        # Build citations
        citations = [
            {
                "index": i,
                "document_id": c.get("document_id", ""),
                "chunk_id": c.get("id", ""),
                "section": c.get("section_path", ""),
                "page": c.get("page_range", ""),
                "quote": c.get("content", "")[:200],
            }
            for i, c in enumerate(chunks[:5], 1)
        ]

        # Confidence: lower when contradictions exist
        base_confidence = min(1.0, 0.6 + 0.08 * len(chunks))
        if contradictions:
            penalty = 0.15 * len(contradictions)
            confidence = max(0.2, base_confidence - penalty)
        else:
            confidence = base_confidence

        ctx["answer"] = "\n".join(answer_parts)
        ctx["citations"] = citations
        ctx["contradictions"] = [
            {
                "chunk_a_id": c.chunk_a_id,
                "chunk_b_id": c.chunk_b_id,
                "chunk_a_section": c.chunk_a_section,
                "chunk_b_section": c.chunk_b_section,
                "type": c.contradiction_type,
                "resolution_hint": c.resolution_hint,
            }
            for c in contradictions
        ]
        ctx["confidence"] = confidence

        logger.info(
            "ContradictionAwareOp: %d chunks, %d contradictions, confidence=%.2f",
            len(chunks),
            len(contradictions),
            confidence,
        )
        return ctx
