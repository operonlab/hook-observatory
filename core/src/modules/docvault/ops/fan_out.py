"""FanOutOp — parallel query dispatch to memvault and docvault.

Pipeline C uses this to search both knowledge stores simultaneously,
then merge results downstream via MergeOp.
"""

import asyncio
import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)


class FanOutOp:
    """Fixed Op: query → parallel(memvault, docvault) results."""

    def __init__(
        self,
        *,
        memvault_pipeline: Any | None = None,
        docvault_pipeline: Any | None = None,
    ) -> None:
        self._memvault_pipeline = memvault_pipeline
        self._docvault_pipeline = docvault_pipeline

    @property
    def name(self) -> str:
        return "fan_out"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("query", "space_id")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("memvault_results", "docvault_results")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        tasks = []

        if self._memvault_pipeline is not None:
            mv_ctx = copy.deepcopy(ctx)
            tasks.append(("memvault", self._memvault_pipeline(mv_ctx)))
        else:
            tasks.append(("memvault", self._noop_results()))

        if self._docvault_pipeline is not None:
            dv_ctx = copy.deepcopy(ctx)
            tasks.append(("docvault", self._docvault_pipeline(dv_ctx)))
        else:
            tasks.append(("docvault", self._noop_results()))

        labels = [t[0] for t in tasks]
        coros = [t[1] for t in tasks]
        results = await asyncio.gather(*coros, return_exceptions=True)

        for label, result in zip(labels, results, strict=True):
            if isinstance(result, Exception):
                logger.error("FanOut %s pipeline failed: %s", label, result)
                ctx[f"{label}_results"] = []
            elif isinstance(result, dict):
                ctx[f"{label}_results"] = result.get(
                    "reranked_chunks", result.get("candidate_chunks", [])
                )
            else:
                ctx[f"{label}_results"] = []

        logger.debug(
            "FanOut: memvault=%d, docvault=%d",
            len(ctx.get("memvault_results", [])),
            len(ctx.get("docvault_results", [])),
        )
        return ctx

    @staticmethod
    async def _noop_results() -> dict[str, Any]:
        return {"reranked_chunks": []}
