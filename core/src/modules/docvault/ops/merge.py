"""MergeOp — merge and rank results from multiple sources.

Combines docvault and memvault search results into a unified ranked list
with source attribution tags. Uses score-based interleaving.

Operator protocol:
  input_keys: ("docvault_results", "memvault_results")
  output_keys: ("evidence_chunks", "merge_metadata")
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def merge_results(
    docvault_results: list[dict[str, Any]],
    memvault_results: list[dict[str, Any]],
    max_total: int = 10,
) -> list[dict[str, Any]]:
    """Merge two result sets by score, preserving source tags.

    Uses simple score-based sorting. Both result sets must have a "score" field.
    Each result is tagged with its source for downstream display.
    """
    combined: list[dict[str, Any]] = []

    for r in docvault_results:
        entry = {**r, "source": "docvault"}
        combined.append(entry)

    for r in memvault_results:
        entry = {**r, "source": "memvault"}
        combined.append(entry)

    # Sort by score descending
    combined.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    return combined[:max_total]


class MergeOp:
    """Merge docvault + memvault results into unified ranked list.

    Operator protocol:
      input_keys: ("docvault_results", "memvault_results")
      output_keys: ("evidence_chunks", "merge_metadata")
    """

    def __init__(self, max_total: int = 10) -> None:
        self._max_total = max_total

    @property
    def name(self) -> str:
        return "merge"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("docvault_results", "memvault_results")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("evidence_chunks", "merge_metadata")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        docvault_results: list[dict[str, Any]] = ctx.get("docvault_results", [])
        memvault_results: list[dict[str, Any]] = ctx.get("memvault_results", [])

        merged = merge_results(docvault_results, memvault_results, self._max_total)

        docvault_count = sum(1 for r in merged if r.get("source") == "docvault")
        memvault_count = sum(1 for r in merged if r.get("source") == "memvault")

        ctx["evidence_chunks"] = merged
        ctx["merge_metadata"] = {
            "total": len(merged),
            "docvault_count": docvault_count,
            "memvault_count": memvault_count,
            "max_total": self._max_total,
        }

        logger.info(
            "MergeOp: %d docvault + %d memvault → %d merged",
            len(docvault_results),
            len(memvault_results),
            len(merged),
        )
        return ctx
