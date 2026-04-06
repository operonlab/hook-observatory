"""FanOutOp — parallel search across docvault and memvault.

Used in Pipeline B (mixed mode) to retrieve from both knowledge stores
concurrently. Results are passed to MergeOp for unification.

Operator protocol:
  input_keys: ("query", "layer_plan")
  output_keys: ("docvault_results", "memvault_results")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.shared.qdrant_search import hybrid_search
from src.shared.search_types import SearchConfig

logger = logging.getLogger(__name__)

DOCVAULT_SERVICE_ID = "docvault-chunk"
MEMVAULT_SERVICE_ID = "memvault-block"


async def _search_docvault(
    query: str,
    space_id: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """Search docvault chunks via hybrid search."""
    config = SearchConfig(service_id=DOCVAULT_SERVICE_ID, top_k=top_k, min_score=0.1)
    try:
        results = await hybrid_search(query, space_id, config)
        return [
            {
                "id": r.id,
                "content": r.content,
                "score": r.score,
                "source": "docvault",
                "document_id": r.metadata.get("entity_id", ""),
                "section_path": r.metadata.get("section_path", ""),
                "page_range": r.metadata.get("page_range", ""),
            }
            for r in results
        ]
    except Exception as e:
        logger.error("FanOutOp: docvault search failed: %s", e)
        return []


async def _search_memvault(
    query: str,
    space_id: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """Search memvault blocks via hybrid search."""
    config = SearchConfig(service_id=MEMVAULT_SERVICE_ID, top_k=top_k, min_score=0.1)
    try:
        results = await hybrid_search(query, space_id, config)
        return [
            {
                "id": r.id,
                "content": r.content,
                "score": r.score,
                "source": "memvault",
                "block_type": r.metadata.get("block_type", ""),
                "tags": r.metadata.get("tags", []),
            }
            for r in results
        ]
    except Exception as e:
        logger.error("FanOutOp: memvault search failed: %s", e)
        return []


class FanOutOp:
    """Parallel search across docvault + memvault.

    Operator protocol:
      input_keys: ("query", "layer_plan")
      output_keys: ("docvault_results", "memvault_results")
    """

    @property
    def name(self) -> str:
        return "fan_out"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("query", "layer_plan")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("docvault_results", "memvault_results")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        query: str = ctx.get("query", "")
        space_id: str = ctx.get("space_id", "default")
        layer_plan: dict[str, Any] = ctx.get("layer_plan", {})

        doc_top_k = layer_plan.get("docvault_top_k", 6)
        mem_top_k = layer_plan.get("memvault_top_k", 4)

        sources = layer_plan.get("sources", ["docvault"])

        # Fan out concurrently
        doc_coro = _search_docvault(query, space_id, doc_top_k)

        if "memvault" in sources:
            mem_coro = _search_memvault(query, space_id, mem_top_k)
            doc_res, mem_res = await asyncio.gather(doc_coro, mem_coro, return_exceptions=True)
        else:
            doc_res = await doc_coro
            mem_res = []

        docvault_results = doc_res if isinstance(doc_res, list) else []
        memvault_results = mem_res if isinstance(mem_res, list) else []

        ctx["docvault_results"] = docvault_results
        ctx["memvault_results"] = memvault_results

        logger.info(
            "FanOutOp: query=%r → docvault=%d, memvault=%d",
            query[:60],
            len(docvault_results),
            len(memvault_results),
        )
        return ctx
