"""CoverageGapOp — detect and record coverage gaps from CRAG verdicts.

When a QA pipeline produces a CRAG verdict of "incorrect" or "ambiguous",
this Op creates a gap record and emits a COVERAGE_GAP_DETECTED event
for the Bottom-Up pipeline to process.

Operator protocol:
  input_keys: ("question", "crag_verdict", "evidence_chunks")
  output_keys: ("gap_record", "gap_emitted")
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from src.events.bus import event_bus
from src.events.types import DocvaultEvents

logger = logging.getLogger(__name__)

# CRAG verdicts that trigger gap detection
GAP_VERDICTS = {"incorrect", "ambiguous"}


def _compute_query_hash(query: str) -> str:
    """Compute SHA-256 hash of normalized query for dedup."""
    normalized = query.strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _infer_gap_type(
    verdict: str,
    chunks: list[dict[str, Any]],
) -> str:
    """Infer gap type from CRAG verdict and evidence quality."""
    if not chunks:
        return "topic_missing"

    if verdict == "incorrect":
        # Had results but they were wrong → likely outdated
        return "outdated"

    # "ambiguous" with some results → depth issue
    return "depth_insufficient"


class CoverageGapOp:
    """Detect coverage gaps and emit events for Bottom-Up pipeline.

    Operator protocol:
      input_keys: ("question", "crag_verdict", "evidence_chunks")
      output_keys: ("gap_record", "gap_emitted")
    """

    @property
    def name(self) -> str:
        return "coverage_gap"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("question", "crag_verdict", "evidence_chunks")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("gap_record", "gap_emitted")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        question: str = ctx.get("question", "")
        verdict: str = ctx.get("crag_verdict", "correct")
        chunks: list[dict[str, Any]] = ctx.get("evidence_chunks", [])

        if verdict not in GAP_VERDICTS:
            ctx["gap_record"] = None
            ctx["gap_emitted"] = False
            return ctx

        gap_type = _infer_gap_type(verdict, chunks)
        query_hash = _compute_query_hash(question)

        gap_record: dict[str, Any] = {
            "query_text": question,
            "query_hash": query_hash,
            "detected_at": datetime.now(UTC).isoformat(),
            "gap_type": gap_type,
            "crag_verdict": verdict,
            "evidence_count": len(chunks),
            "status": "pending",
        }

        ctx["gap_record"] = gap_record
        ctx["gap_emitted"] = False

        # Emit event for async processing (fire-and-forget)
        try:
            event_data = {
                "gap": gap_record,
                "space_id": ctx.get("space_id", "default"),
            }
            asyncio.get_running_loop().create_task(
                event_bus.publish(DocvaultEvents.COVERAGE_GAP_DETECTED, event_data)
            )
            ctx["gap_emitted"] = True
        except Exception as e:
            logger.warning("CoverageGapOp: failed to emit event: %s", e)

        logger.info(
            "CoverageGapOp: verdict=%s → gap_type=%s, query=%r",
            verdict,
            gap_type,
            question[:60],
        )
        return ctx
