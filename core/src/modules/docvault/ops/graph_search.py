"""GraphSearchOp — KG-enhanced search combining vector recall with HiRAG L2→L1→L0 cascade.

Extends standard hybrid vector search (HybridRRFSearchOp) with knowledge-graph traversal
to improve recall on scattered-wisdom queries where relevant chunks may not be
surface-similar to the query but are topically connected via entity communities.

HiRAG three-layer cascade:
  L2 = community summaries (Qdrant-indexed, searched by query)
  L1 = community membership (DocCommunityTriple join table)
  L0 = individual triples → chunk_id back-references

Operator protocol:
  input_keys:  ("query", "space_id")          # expanded_queries + top_k optional
  output_keys: ("evidence_chunks", "search_metadata")

Degradation guarantee:
  - No DB (ctx["db"] absent) → falls back to vector-only search
  - Any graph stage fails → logs warning, continues with partial results
  - Empty community hits → skips graph path entirely, no DB queries
"""

from __future__ import annotations

import logging
from typing import Any

from src.shared.qdrant_search import hybrid_search
from src.shared.search_types import SearchConfig

from .hybrid_rrf_search import HybridRRFSearchOp

logger = logging.getLogger(__name__)

# Qdrant service ID for L2 community summaries
_COMMUNITY_SERVICE_ID = "docvault-community"

# Base relevance score assigned to graph-sourced chunks (no vector score available)
_GRAPH_BASE_SCORE = 0.5

# Score boost applied when a chunk appears in BOTH vector results and graph path
# Dual-source corroboration is strong signal for factual QA
_OVERLAP_BOOST = 0.25


class GraphSearchOp:
    """KG-enhanced search: vector recall + HiRAG L2→L1→L0 graph traversal.

    Stage 1 — Vector search:
        Delegates to HybridRRFSearchOp for dense+sparse hybrid recall.
        These results are the high-confidence seed set.

    Stage 2 — Graph recall (requires ctx["db"]):
        2a. Embed query into L2 community summary space (Qdrant).
        2b. Retrieve community IDs from top-k summary hits.
        2c. L1: resolve communities → triple IDs via DocCommunityTriple.
        2d. L0: resolve triple IDs → chunk IDs via DocTriple.chunk_id.
        2e. Fetch chunk records from DocumentChunk table.

    Stage 3 — Merge + RRF dedup:
        Vector results take precedence (higher confidence).
        Graph-only chunks are appended with base score.
        Chunks appearing in both sets receive an overlap boost.
        Final list sorted by score descending, capped at top_k.

    Operator protocol:
      input_keys:  ("query", "space_id")
      output_keys: ("evidence_chunks", "search_metadata")
    """

    def __init__(self, top_k: int = 10) -> None:
        self._top_k = top_k

    @property
    def name(self) -> str:
        return "graph_search"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("query", "space_id")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("evidence_chunks", "search_metadata")

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        query: str = ctx.get("query", "")
        space_id: str = ctx.get("space_id", "default")
        top_k: int = ctx.get("top_k", self._top_k)

        if not query.strip():
            ctx["evidence_chunks"] = []
            ctx["search_metadata"] = {"total": 0}
            return ctx

        # ----------------------------------------------------------
        # Stage 1: Standard vector search (always runs)
        # ----------------------------------------------------------
        vector_results = await self._run_vector_search(ctx, query, space_id, top_k)
        for r in vector_results:
            r["source"] = "vector"

        # ----------------------------------------------------------
        # Stage 2: Graph-enhanced recall (optional, requires DB)
        # ----------------------------------------------------------
        db = ctx.get("db")
        graph_results: list[dict[str, Any]] = []
        community_ids: list[str] = []

        if db is not None:
            try:
                community_ids, graph_results = await self._run_graph_recall(
                    db, query, space_id
                )
            except Exception as exc:
                logger.warning(
                    "GraphSearchOp: graph recall failed, falling back to vector-only: %s",
                    exc,
                )
                graph_results = []
                community_ids = []
        else:
            logger.debug(
                "GraphSearchOp: no db in ctx — skipping graph recall (vector-only mode)"
            )

        # ----------------------------------------------------------
        # Stage 3: Merge + RRF dedup
        # ----------------------------------------------------------
        merged = self._merge(vector_results, graph_results, top_k)

        ctx["evidence_chunks"] = merged
        ctx["search_metadata"] = {
            "vector_count": len(vector_results),
            "graph_count": len(graph_results),
            "merged_count": len(merged),
            "graph_communities_hit": len(community_ids),
            "top_k": top_k,
        }

        logger.info(
            "GraphSearchOp: vector=%d graph=%d merged=%d communities=%d",
            len(vector_results),
            len(graph_results),
            len(merged),
            len(community_ids),
        )
        return ctx

    # ------------------------------------------------------------------
    # Stage 1 helper
    # ------------------------------------------------------------------

    async def _run_vector_search(
        self,
        ctx: dict[str, Any],
        query: str,
        space_id: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Delegate to HybridRRFSearchOp; return evidence_chunks list."""
        vector_op = HybridRRFSearchOp()
        vector_ctx: dict[str, Any] = {
            "query": query,
            "expanded_queries": ctx.get("expanded_queries"),
            "space_id": space_id,
            "top_k": top_k,
        }
        try:
            await vector_op(vector_ctx)
        except Exception as exc:
            logger.error("GraphSearchOp: vector search failed: %s", exc)
            return []
        return vector_ctx.get("evidence_chunks", [])

    # ------------------------------------------------------------------
    # Stage 2 helper
    # ------------------------------------------------------------------

    async def _run_graph_recall(
        self,
        db: Any,
        query: str,
        space_id: str,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """L2→L1→L0 cascade; returns (community_ids, chunk_dicts)."""
        from sqlalchemy import select

        from ..kg_models import DocCommunityTriple, DocTriple
        from ..models import DocumentChunk

        # 2a. Search L2 community summaries in Qdrant
        config = SearchConfig(top_k=5, service_ids=[_COMMUNITY_SERVICE_ID])
        try:
            summary_results, _ = await hybrid_search(query, space_id, config)
        except Exception as exc:
            logger.debug("GraphSearchOp: community summary search failed: %s", exc)
            summary_results = []

        community_ids: list[str] = [r.entity_id for r in summary_results]
        if not community_ids:
            return [], []

        # 2c. L1: communities → triple IDs
        ct_stmt = select(DocCommunityTriple.triple_id).where(
            DocCommunityTriple.community_id.in_(community_ids),
            DocCommunityTriple.deleted_at == None,  # noqa: E711
        )
        triple_ids = (await db.execute(ct_stmt)).scalars().all()
        if not triple_ids:
            return community_ids, []

        # 2d. L0: triples → chunk IDs
        t_stmt = select(DocTriple.chunk_id).where(
            DocTriple.id.in_(triple_ids),
            DocTriple.chunk_id != None,  # noqa: E711
            DocTriple.deleted_at == None,  # noqa: E711
        )
        chunk_ids = list(set((await db.execute(t_stmt)).scalars().all()))
        if not chunk_ids:
            return community_ids, []

        # 2e. Fetch chunk records
        c_stmt = select(
            DocumentChunk.id,
            DocumentChunk.content,
            DocumentChunk.document_id,
            DocumentChunk.section_path,
            DocumentChunk.page_range,
            DocumentChunk.heading,
            DocumentChunk.chunk_index,
            DocumentChunk.version_id,
        ).where(
            DocumentChunk.id.in_(chunk_ids),
            DocumentChunk.deleted_at == None,  # noqa: E711
        )
        chunk_rows = (await db.execute(c_stmt)).all()

        graph_results: list[dict[str, Any]] = []
        for row in chunk_rows:
            graph_results.append(
                {
                    "id": row.id,
                    "content": row.content,
                    "score": _GRAPH_BASE_SCORE,
                    "document_id": row.document_id,
                    "section_path": row.section_path or "",
                    "page_range": row.page_range or "",
                    "heading": row.heading or "",
                    "chunk_index": row.chunk_index,
                    "version_id": row.version_id,
                    "source": "graph",
                }
            )

        return community_ids, graph_results

    # ------------------------------------------------------------------
    # Stage 3 helper
    # ------------------------------------------------------------------

    @staticmethod
    def _merge(
        vector_results: list[dict[str, Any]],
        graph_results: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Merge vector + graph results with RRF-style overlap boost."""
        seen_ids: set[str] = set()
        merged: list[dict[str, Any]] = []

        # Vector results first — higher-confidence seed set
        for r in vector_results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                merged.append(r)

        # Graph results: append new, boost overlapping
        for r in graph_results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                merged.append(r)
            else:
                # Chunk already in vector results — apply overlap score boost
                for m in merged:
                    if m["id"] == r["id"]:
                        m["score"] = min(1.0, m["score"] + _OVERLAP_BOOST)
                        break

        merged.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return merged[:top_k]
