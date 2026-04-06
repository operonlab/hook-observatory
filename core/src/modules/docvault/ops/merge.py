"""MergeOp — confidence-weighted merge of multi-source results.

Combines results from memvault and docvault (Pipeline C),
de-duplicates by content similarity, and tags sources.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Similarity threshold for de-duplication (Jaccard on word sets)
DEDUP_THRESHOLD = 0.7


class MergeOp:
    """Fixed Op: two result sets → unified ranked + source tags."""

    @property
    def name(self) -> str:
        return "merge"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("memvault_results", "docvault_results")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("candidate_chunks", "source_distribution")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        mv_results: list[dict] = ctx.get("memvault_results", [])
        dv_results: list[dict] = ctx.get("docvault_results", [])

        # Tag sources
        for r in mv_results:
            r["source"] = "memvault"
        for r in dv_results:
            r["source"] = "docvault"

        # Interleave by score
        all_results = sorted(
            mv_results + dv_results,
            key=lambda x: x.get("rerank_score", x.get("score", 0.0)),
            reverse=True,
        )

        # De-duplicate by content similarity
        merged = self._dedup(all_results)

        ctx["candidate_chunks"] = merged
        ctx["source_distribution"] = {
            "memvault": sum(1 for r in merged if r.get("source") == "memvault"),
            "docvault": sum(1 for r in merged if r.get("source") == "docvault"),
            "total": len(merged),
        }
        logger.debug(
            "Merge: %d mv + %d dv → %d merged",
            len(mv_results),
            len(dv_results),
            len(merged),
        )
        return ctx

    def _dedup(self, results: list[dict]) -> list[dict]:
        """Remove near-duplicate results using word-level Jaccard similarity."""
        kept: list[dict] = []
        kept_word_sets: list[set[str]] = []

        for result in results:
            words = set(result.get("content", "").lower().split())
            if not words:
                continue

            is_dup = False
            for existing_words in kept_word_sets:
                intersection = words & existing_words
                union = words | existing_words
                if union and len(intersection) / len(union) > DEDUP_THRESHOLD:
                    is_dup = True
                    break

            if not is_dup:
                kept.append(result)
                kept_word_sets.append(words)

        return kept
