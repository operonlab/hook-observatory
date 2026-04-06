"""CoverageGapOp — detect coverage gaps from CRAG verdicts.

When CRAG verdict is INCORRECT or confidence is low, record a coverage gap
for the Bottom-Up pipeline (Pipeline B) to address.
"""

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.3


class CoverageGapOp:
    """Fixed Op: CRAG verdict → gap_record + event."""

    @property
    def name(self) -> str:
        return "coverage_gap"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("query", "answer_confidence")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("gap_detected", "gap_record")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        query: str = ctx["query"]
        confidence: float = ctx.get("answer_confidence", 0.0)
        crag_verdict: str = ctx.get("crag_verdict", "correct")

        # Detect gap conditions
        is_gap = crag_verdict == "incorrect" or confidence < CONFIDENCE_THRESHOLD
        ctx["gap_detected"] = is_gap

        if not is_gap:
            ctx["gap_record"] = None
            return ctx

        # Determine gap type
        if crag_verdict == "incorrect":
            gap_type = "topic_missing"
        elif confidence < CONFIDENCE_THRESHOLD * 0.5:
            gap_type = "topic_missing"
        else:
            gap_type = "depth_insufficient"

        query_hash = hashlib.sha256(query.encode()).hexdigest()
        gap_record = {
            "query_text": query,
            "query_hash": query_hash,
            "detected_at": datetime.now(UTC).isoformat(),
            "gap_type": gap_type,
            "status": "pending",
            "confidence_at_detection": confidence,
            "crag_verdict": crag_verdict,
        }

        ctx["gap_record"] = gap_record
        logger.info(
            "CoverageGap detected: type=%s, confidence=%.2f, query=%r",
            gap_type,
            confidence,
            query[:60],
        )
        return ctx
