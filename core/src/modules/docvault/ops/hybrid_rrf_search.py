"""HybridRRFSearchOp — Qdrant hybrid search with Reciprocal Rank Fusion.

SearchSlot: query_embedding → candidate chunks + scores.
Wraps shared qdrant_search.hybrid_search() with docvault-specific config.
"""

import logging
from typing import Any

from src.shared import qdrant_search
from src.shared.embedding import get_embedding
from src.shared.search_types import SearchConfig

logger = logging.getLogger(__name__)

SERVICE_ID = "docvault-chunk"


class HybridRRFSearchOp:
    """SearchSlot: query → candidate_chunks via Qdrant RRF."""

    @property
    def name(self) -> str:
        return "hybrid_rrf_search"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("query", "space_id")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("candidate_chunks", "search_scores")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        query: str = ctx["query"]
        space_id: str = ctx["space_id"]
        layer_plan: dict = ctx.get("layer_plan", {})
        top_k: int = layer_plan.get("search_top_k", 10)

        # Embed query
        query_embedding = await get_embedding(query, task_type="search_query")
        if query_embedding is None:
            logger.warning("Query embedding failed, returning empty results")
            ctx["candidate_chunks"] = []
            ctx["search_scores"] = []
            return ctx

        config = SearchConfig(
            service_id=SERVICE_ID,
            space_id=space_id,
            top_k=top_k,
        )

        results = await qdrant_search.hybrid_search(
            query_text=query,
            query_embedding=query_embedding,
            config=config,
        )

        ctx["candidate_chunks"] = [
            {
                "entity_id": r.entity_id,
                "content": r.content,
                "score": r.score,
                "metadata": r.metadata,
            }
            for r in results
        ]
        ctx["search_scores"] = [r.score for r in results]
        logger.debug("HybridRRF: %d candidates for query=%r", len(results), query[:60])
        return ctx
