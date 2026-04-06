"""HybridRRFSearchOp — hybrid dense+sparse search with RRF fusion.

Wraps shared/qdrant_search.py hybrid_search with docvault-specific
configuration (service_id filter, RRF parameters).

Operator protocol:
  input_keys: ("query",)
  output_keys: ("evidence_chunks", "search_metadata")
"""

from __future__ import annotations

import logging
from typing import Any

from src.shared.qdrant_search import hybrid_search
from src.shared.search_types import SearchConfig

logger = logging.getLogger(__name__)

SERVICE_ID = "docvault-chunk"


class HybridRRFSearchOp:
    """Hybrid dense+sparse search for docvault chunks.

    Uses RRF (Reciprocal Rank Fusion) to merge dense embedding results
    with sparse BM25-style results from Qdrant.

    Operator protocol:
      input_keys: ("query",)
      output_keys: ("evidence_chunks", "search_metadata")
    """

    def __init__(
        self,
        top_k: int = 10,
        min_score: float = 0.1,
    ) -> None:
        self._top_k = top_k
        self._min_score = min_score

    @property
    def name(self) -> str:
        return "hybrid_rrf_search"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("query",)

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("evidence_chunks", "search_metadata")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        query: str = ctx.get("query", "")
        space_id: str = ctx.get("space_id", "default")
        top_k = ctx.get("top_k", self._top_k)

        if not query.strip():
            ctx["evidence_chunks"] = []
            ctx["search_metadata"] = {"total": 0}
            return ctx

        config = SearchConfig(
            service_id=SERVICE_ID,
            top_k=top_k,
            min_score=self._min_score,
        )

        try:
            results = await hybrid_search(query, space_id, config)
        except Exception as e:
            logger.error("HybridRRFSearchOp: search failed: %s", e)
            ctx["evidence_chunks"] = []
            ctx["search_metadata"] = {"total": 0, "error": str(e)}
            return ctx

        # Convert SearchResult to chunk dicts for downstream ops
        evidence_chunks: list[dict[str, Any]] = []
        for r in results:
            chunk: dict[str, Any] = {
                "id": r.id,
                "content": r.content,
                "score": r.score,
                "document_id": r.metadata.get("entity_id", ""),
                "section_path": r.metadata.get("section_path", ""),
                "page_range": r.metadata.get("page_range", ""),
                "heading": r.metadata.get("heading", ""),
                "chunk_index": r.metadata.get("chunk_index", 0),
                "version_id": r.metadata.get("version_id", ""),
                "created_at": r.metadata.get("created_at", ""),
            }
            evidence_chunks.append(chunk)

        ctx["evidence_chunks"] = evidence_chunks
        ctx["search_metadata"] = {
            "total": len(evidence_chunks),
            "service_id": SERVICE_ID,
            "top_k": top_k,
        }

        logger.info(
            "HybridRRFSearchOp: query=%r → %d results",
            query[:60],
            len(evidence_chunks),
        )
        return ctx
