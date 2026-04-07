"""IntentRouterOp — classify query intent and plan retrieval layers.

Routes incoming queries to the appropriate pipeline (A/B/C) based on intent:
  - A: Pure docvault factual (single-source QA)
  - B: Mixed docvault + memvault (needs fan-out)
  - C: Coverage gap trigger (insufficient docs detected)

Operator protocol:
  input_keys: ("query",)
  output_keys: ("intent", "layer_plan")
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Intent classification heuristics (LLM-based in Phase 2)
_PERSONAL_PATTERNS = re.compile(
    r"(我的|my |偏好|preference|attitude|attitude|習慣|profile|"
    r"我之前|我記得|上次|last time|remember)",
    re.IGNORECASE,
)

_FACTUAL_PATTERNS = re.compile(
    r"(什麼是|what is|how does|how to|定義|definition|"
    r"規定|regulation|法規|policy|根據|according to|"
    r"哪一條|which article|第\d+條)",
    re.IGNORECASE,
)


def classify_intent(query: str) -> str:
    """Classify query intent into pipeline type.

    Returns:
        "factual" — pure document QA (Pipeline A)
        "mixed" — needs both docvault + memvault (Pipeline B)
        "meta" — coverage / gap analysis query
    """
    q = query.strip()

    if _PERSONAL_PATTERNS.search(q):
        return "mixed"

    if _FACTUAL_PATTERNS.search(q):
        return "factual"

    # Default: factual for docvault queries
    return "factual"


def build_layer_plan(intent: str, query: str) -> dict[str, Any]:
    """Build retrieval layer plan based on classified intent.

    Returns a dict describing which sources to query and in what order.
    """
    if intent == "mixed":
        return {
            "pipeline": "B",
            "sources": ["docvault", "memvault"],
            "strategy": "fan_out_merge",
            "docvault_top_k": 15,
            "memvault_top_k": 6,
            "synth_top_k": 8,
        }

    if intent == "meta":
        return {
            "pipeline": "C",
            "sources": ["docvault"],
            "strategy": "coverage_check",
            "docvault_top_k": 20,
            "synth_top_k": 10,
        }

    # Default: factual — over-retrieve for reranking
    return {
        "pipeline": "A",
        "sources": ["docvault"],
        "strategy": "direct_search",
        "docvault_top_k": 20,
        "synth_top_k": 8,
    }


class IntentRouterOp:
    """Route query to appropriate retrieval pipeline.

    Operator protocol:
      input_keys: ("query",)
      output_keys: ("intent", "layer_plan")
    """

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
        query: str = ctx.get("query", "")
        intent = classify_intent(query)
        layer_plan = build_layer_plan(intent, query)

        ctx["intent"] = intent
        ctx["layer_plan"] = layer_plan

        logger.info(
            "IntentRouterOp: query=%r → intent=%s, pipeline=%s",
            query[:60],
            intent,
            layer_plan["pipeline"],
        )
        return ctx
