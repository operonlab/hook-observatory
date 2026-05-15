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
        score_threshold: float = 0.0,
    ) -> None:
        self._top_k = top_k
        self._score_threshold = score_threshold

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

        # Multi-query: search expanded queries if available, else just the original
        queries = ctx.get("expanded_queries", [query])
        if not queries:
            queries = [query]

        per_query_k = max(top_k // len(queries), 5)
        tag_filter: list[str] | None = ctx.get("tag_filter")
        config = SearchConfig(
            service_ids=[SERVICE_ID],
            top_k=per_query_k,
            score_threshold=self._score_threshold,
            tag_filter=tag_filter,
        )

        # Search all queries, deduplicate by entity_id
        seen_ids: set[str] = set()
        evidence_chunks: list[dict[str, Any]] = []

        for q in queries:
            try:
                results, _meta = await hybrid_search(q, space_id, config)
            except Exception as e:
                logger.error("HybridRRFSearchOp: search failed for %r: %s", q[:40], e)
                continue

            for r in results:
                if r.entity_id in seen_ids:
                    continue
                seen_ids.add(r.entity_id)
                evidence_chunks.append(
                    {
                        "id": r.entity_id,
                        "content": r.content_preview,
                        "score": r.score,
                        "document_id": r.metadata.get("document_id", r.entity_id),
                        "section_path": r.metadata.get("section_path", ""),
                        "page_range": r.metadata.get("page_range", ""),
                        "heading": r.metadata.get("heading", ""),
                        "chunk_index": r.metadata.get("chunk_index"),
                        "version_id": r.metadata.get("version_id", ""),
                        "created_at": r.metadata.get("created_at", ""),
                    }
                )

        # Sort by score descending, cap at top_k
        evidence_chunks.sort(key=lambda c: c.get("score", 0), reverse=True)
        evidence_chunks = evidence_chunks[:top_k]

        ctx["evidence_chunks"] = evidence_chunks
        ctx["search_metadata"] = {
            "total": len(evidence_chunks),
            "service_id": SERVICE_ID,
            "queries_used": len(queries),
            "top_k": top_k,
        }

        logger.info(
            "HybridRRFSearchOp: %d queries → %d unique results (top_k=%d)",
            len(queries),
            len(evidence_chunks),
            top_k,
        )
        return ctx
