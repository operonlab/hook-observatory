"""GapAnalyzerOp — analyze coverage gaps and suggest remediation sources.

Processes gap records from CoverageGapOp and produces actionable
suggestions for closing the gap: potential sources, gap classification,
and recommended actions.

Operator protocol:
  input_keys: ("gap_record",)
  output_keys: ("suggested_sources", "gap_analysis")
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Source suggestion templates by gap type
_SOURCE_SUGGESTIONS: dict[str, list[dict[str, str]]] = {
    "topic_missing": [
        {"type": "web_search", "action": "Search for authoritative sources on the topic"},
        {"type": "manual_upload", "action": "Request domain expert to upload relevant documents"},
        {"type": "api_fetch", "action": "Check connected APIs for coverage"},
    ],
    "depth_insufficient": [
        {"type": "expand_existing", "action": "Find more detailed versions of existing sources"},
        {"type": "related_docs", "action": "Search for supplementary materials"},
    ],
    "outdated": [
        {"type": "supersede", "action": "Find and upload newer version of the document"},
        {"type": "verify", "action": "Cross-check with official/primary sources"},
    ],
}


def analyze_gap(gap: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Analyze a coverage gap and produce suggestions.

    Returns (suggested_sources, analysis_metadata).
    """
    gap_type = gap.get("gap_type", "topic_missing")
    query_text = gap.get("query_text", "")
    evidence_count = gap.get("evidence_count", 0)

    suggested = _SOURCE_SUGGESTIONS.get(gap_type, _SOURCE_SUGGESTIONS["topic_missing"])

    # Build analysis
    analysis: dict[str, Any] = {
        "gap_type": gap_type,
        "severity": _assess_severity(gap_type, evidence_count),
        "query_keywords": _extract_keywords(query_text),
        "recommended_action": suggested[0]["action"] if suggested else "Manual review required",
        "evidence_count": evidence_count,
    }

    return suggested, analysis


def _assess_severity(gap_type: str, evidence_count: int) -> str:
    """Assess gap severity: high / medium / low."""
    if gap_type == "topic_missing" and evidence_count == 0:
        return "high"
    if gap_type == "outdated":
        return "high"
    if gap_type == "depth_insufficient":
        return "medium"
    return "low"


def _extract_keywords(query: str) -> list[str]:
    """Extract key terms from query for source search.

    Simple whitespace tokenization — LLM extraction in Phase 2.
    """
    stopwords = {"is", "the", "a", "an", "what", "how", "does", "do", "are", "was",
                 "的", "是", "什麼", "哪個", "如何", "怎麼"}
    words = query.lower().split()
    return [w for w in words if len(w) > 2 and w not in stopwords][:8]


class GapAnalyzerOp:
    """Analyze coverage gap and suggest sources for remediation.

    Operator protocol:
      input_keys: ("gap_record",)
      output_keys: ("suggested_sources", "gap_analysis")
    """

    @property
    def name(self) -> str:
        return "gap_analyzer"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("gap_record",)

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("suggested_sources", "gap_analysis")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        gap_record = ctx.get("gap_record")

        if not gap_record:
            ctx["suggested_sources"] = []
            ctx["gap_analysis"] = {}
            return ctx

        suggested, analysis = analyze_gap(gap_record)

        ctx["suggested_sources"] = suggested
        ctx["gap_analysis"] = analysis

        logger.info(
            "GapAnalyzerOp: gap_type=%s, severity=%s, %d suggestions",
            analysis.get("gap_type"),
            analysis.get("severity"),
            len(suggested),
        )
        return ctx
