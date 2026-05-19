"""JinaRerankOp — cross-encoder reranking for docvault search results.

Wraps shared/rerank_utils.py rerank_generic to rerank evidence chunks
using the Jina Reranker v3 MLX worker.

Operator protocol:
  input_keys: ("query", "evidence_chunks")
  output_keys: ("evidence_chunks",)
"""

from __future__ import annotations

import logging
from typing import Any

from src.shared.rerank_utils import rerank_generic

logger = logging.getLogger(__name__)


# Authority-aware reweighting factors (Phase 1 of authority-aware retrieval).
# Applied after cross-encoder rerank: final = ce_blended * doc_weight * role_factor.
# Tuned via regression set; see plans/agent-docvault-smart-search-buzzing-bird.md.
ROLE_FACTOR: dict[str, float] = {
    "invariant": 1.10,
    "open-decision": 1.05,
    "decision-rationale": 1.00,
    "reference": 0.90,
    "fallback": 0.55,
    "raw-note": 0.40,
}
DEFAULT_ROLE_FACTOR = 1.00
DEFAULT_DOC_WEIGHT = 0.7


class JinaRerankOp:
    """Cross-encoder reranking of evidence chunks.

    Blends original retrieval score with cross-encoder relevance score
    using configurable weights.

    Operator protocol:
      input_keys: ("query", "evidence_chunks")
      output_keys: ("evidence_chunks",)
    """

    def __init__(
        self,
        max_candidates: int = 20,
        weight_original: float = 0.2,
        weight_rerank: float = 0.8,
    ) -> None:
        self._max_candidates = max_candidates
        self._weight_original = weight_original
        self._weight_rerank = weight_rerank

    @property
    def name(self) -> str:
        return "jina_rerank"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("query", "evidence_chunks")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("evidence_chunks",)

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        query: str = ctx.get("query", "")
        chunks: list[dict[str, Any]] = ctx.get("evidence_chunks", [])

        if len(chunks) <= 1:
            return ctx

        reranked = await rerank_generic(
            query,
            chunks,
            content_fn=lambda c: c.get("content", ""),
            score_fn=lambda c: c.get("score", 0.0),
            set_score_fn=lambda c, s: c.__setitem__("score", s),
            max_candidates=self._max_candidates,
            weight_original=self._weight_original,
            weight_rerank=self._weight_rerank,
        )

        # Authority-aware reweighting: final = ce_blended * doc_weight * role_factor.
        # Chunks without metadata fall back to defaults (back-compat with older indexes).
        for chunk in reranked:
            doc_weight = chunk.get("doc_weight", DEFAULT_DOC_WEIGHT)
            role_factor = ROLE_FACTOR.get(
                chunk.get("source_role"), DEFAULT_ROLE_FACTOR
            )
            chunk["score"] = chunk.get("score", 0.0) * doc_weight * role_factor
        reranked.sort(key=lambda c: c.get("score", 0.0), reverse=True)

        # Truncate to synth_top_k (best N for LLM synthesis)
        synth_top_k = ctx.get("layer_plan", {}).get("synth_top_k")
        if synth_top_k and len(reranked) > synth_top_k:
            reranked = reranked[:synth_top_k]

        ctx["evidence_chunks"] = reranked

        logger.info(
            "JinaRerankOp: reranked %d → %d chunks for query=%r",
            len(chunks),
            len(reranked),
            query[:60],
        )
        return ctx
