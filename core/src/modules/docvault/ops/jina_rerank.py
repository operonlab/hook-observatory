"""JinaRerankOp — cross-encoder reranking via shared rerank_bridge.

RerankSlot: candidate_chunks → reranked_top_k.
Wraps the existing Jina Reranker v3 MLX worker.
"""

import logging
from typing import Any

from src.shared.rerank_bridge import rerank

logger = logging.getLogger(__name__)


class JinaRerankOp:
    """RerankSlot: rerank candidates using Jina cross-encoder."""

    @property
    def name(self) -> str:
        return "jina_rerank"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("query", "candidate_chunks")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("reranked_chunks",)

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        query: str = ctx["query"]
        candidates: list[dict] = ctx["candidate_chunks"]
        layer_plan: dict = ctx.get("layer_plan", {})
        top_k: int = layer_plan.get("rerank_top_k", 5)

        if not candidates:
            ctx["reranked_chunks"] = []
            return ctx

        texts = [c["content"] for c in candidates]
        scores = await rerank(query, texts)

        if scores is None:
            # Fallback: keep original order
            logger.warning("Rerank unavailable, using search order")
            ctx["reranked_chunks"] = candidates[:top_k]
            return ctx

        # Pair with scores and sort descending
        scored = sorted(
            zip(candidates, scores, strict=True),
            key=lambda x: x[1],
            reverse=True,
        )
        reranked = []
        for chunk, score in scored[:top_k]:
            chunk["rerank_score"] = score
            reranked.append(chunk)

        ctx["reranked_chunks"] = reranked
        logger.debug("JinaRerank: %d → %d candidates", len(candidates), len(reranked))
        return ctx
