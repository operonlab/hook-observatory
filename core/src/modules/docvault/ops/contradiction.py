"""ContradictionDetectionOp — detect contradictions across retrieval results.

Fixed Op (not a Slot): runs after reranking to identify conflicting statements
across different documents. Emits RELATION_DISCOVERED event for async KG writes.

Distinct from ContradictionAwareOp (SynthSlot) which handles answer synthesis
with contradiction awareness. This Op is the detection layer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.events.bus import event_bus
from src.events.types import DocvaultEvents
from text_ops.overlap import jaccard_word_overlap as _word_overlap

logger = logging.getLogger(__name__)

# Minimum word overlap to consider two chunks topically related
OVERLAP_THRESHOLD = 0.3
# Minimum number of chunks to trigger pairwise comparison
MIN_CHUNKS_FOR_DETECTION = 2


def detect_contradictions(
    chunks: list[dict[str, Any]],
    overlap_threshold: float = OVERLAP_THRESHOLD,
) -> list[dict[str, Any]]:
    """Detect potential contradictions among ranked chunks.

    Heuristic: high topic overlap (word Jaccard) between chunks from
    different documents suggests potential contradiction.

    Returns:
        List of contradiction dicts with chunk pair info.
    """
    if len(chunks) < MIN_CHUNKS_FOR_DETECTION:
        return []

    contradictions: list[dict[str, Any]] = []

    for i, chunk_a in enumerate(chunks):
        for chunk_b in chunks[i + 1 :]:
            doc_a = chunk_a.get("document_id", "")
            doc_b = chunk_b.get("document_id", "")

            # Only cross-document contradictions
            if doc_a == doc_b or not doc_a or not doc_b:
                continue

            content_a = chunk_a.get("content", "")
            content_b = chunk_b.get("content", "")
            overlap = _word_overlap(content_a, content_b)

            if overlap < overlap_threshold:
                continue

            # Determine contradiction type from timestamps
            created_a = chunk_a.get("created_at", "")
            created_b = chunk_b.get("created_at", "")
            if created_a and created_b and str(created_a) != str(created_b):
                c_type = "temporal"
            else:
                c_type = "direct"

            contradictions.append(
                {
                    "chunk_a_id": chunk_a.get("id", ""),
                    "chunk_b_id": chunk_b.get("id", ""),
                    "document_a_id": doc_a,
                    "document_b_id": doc_b,
                    "section_a": chunk_a.get("section_path", ""),
                    "section_b": chunk_b.get("section_path", ""),
                    "type": c_type,
                    "overlap": round(overlap, 3),
                    "confidence": round(min(overlap * 1.5, 0.9), 3),
                    "resolution_hint": (
                        "Newer document may supersede (lex posterior)"
                        if c_type == "temporal"
                        else "Review both provisions; consider scope and specificity"
                    ),
                }
            )

    return contradictions


class ContradictionDetectionOp:
    """Fixed Op: detect contradictions in evidence chunks and emit events.

    Runs after reranking, before synthesis. Does NOT block the read path
    for relation writes — instead emits RELATION_DISCOVERED event.

    Operator protocol:
        input_keys: ("evidence_chunks",)
        output_keys: ("contradictions", "contradiction_count")
    """

    def __init__(self, overlap_threshold: float = OVERLAP_THRESHOLD) -> None:
        self._overlap_threshold = overlap_threshold

    @property
    def name(self) -> str:
        return "contradiction_detection"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("evidence_chunks",)

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("contradictions", "contradiction_count")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        chunks = ctx.get("evidence_chunks", [])
        contradictions = detect_contradictions(chunks, self._overlap_threshold)

        ctx["contradictions"] = contradictions
        ctx["contradiction_count"] = len(contradictions)

        if contradictions:
            logger.info(
                "ContradictionDetectionOp: found %d contradictions in %d chunks",
                len(contradictions),
                len(chunks),
            )

            # Emit event for async relation writes (fire-and-forget)
            event_data = {
                "contradictions": contradictions,
                "space_id": ctx.get("space_id", "default"),
                "question": ctx.get("question", ""),
            }
            asyncio.get_running_loop().create_task(
                event_bus.publish(DocvaultEvents.RELATION_DISCOVERED, event_data)
            )

        return ctx
