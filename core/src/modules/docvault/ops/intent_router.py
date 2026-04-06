"""IntentRouterOp — classify query intent and build a layer execution plan.

Routes queries to the appropriate search strategy (factual, exploratory, comparative).
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Intent categories
INTENT_FACTUAL = "factual"  # direct answer from docs
INTENT_EXPLORATORY = "exploratory"  # broad topic exploration
INTENT_COMPARATIVE = "comparative"  # compare across documents


class IntentRouterOp:
    """Classify query intent → decide search strategy."""

    @property
    def name(self) -> str:
        return "intent_router"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("query",)

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("intent", "layer_plan")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        query = ctx["query"]
        intent, layer_plan = self._classify(query)
        ctx["intent"] = intent
        ctx["layer_plan"] = layer_plan
        logger.debug("IntentRouter: query=%r → intent=%s", query[:80], intent)
        return ctx

    def _classify(self, query: str) -> tuple[str, dict[str, Any]]:
        """Rule-based intent classification. LLM upgrade in Phase 2+."""
        q_lower = query.lower()

        # Comparative signals
        comparative_signals = ("compare", "vs", "difference", "versus", "比較", "差異", "對比")
        if any(sig in q_lower for sig in comparative_signals):
            return INTENT_COMPARATIVE, {
                "search_top_k": 10,
                "rerank_top_k": 6,
                "multi_doc": True,
            }

        # Exploratory signals
        exploratory_signals = (
            "what is",
            "explain",
            "overview",
            "什麼是",
            "介紹",
            "概述",
            "how does",
        )
        if any(sig in q_lower for sig in exploratory_signals):
            return INTENT_EXPLORATORY, {
                "search_top_k": 8,
                "rerank_top_k": 5,
                "multi_doc": False,
            }

        # Default: factual
        return INTENT_FACTUAL, {
            "search_top_k": 5,
            "rerank_top_k": 3,
            "multi_doc": False,
        }
