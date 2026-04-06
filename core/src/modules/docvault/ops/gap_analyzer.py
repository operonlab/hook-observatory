"""GapAnalyzerOp — analyze coverage gaps and suggest remediation sources.

Takes a gap record and uses LLM to suggest what documents or sources
could fill the knowledge gap.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class GapAnalyzerOp:
    """Fixed Op: gap → suggested_sources + gap_type refinement."""

    @property
    def name(self) -> str:
        return "gap_analyzer"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("gap_record", "query")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("suggested_sources", "refined_gap_type")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        gap_record: dict | None = ctx.get("gap_record")
        query: str = ctx["query"]

        if gap_record is None:
            ctx["suggested_sources"] = []
            ctx["refined_gap_type"] = None
            return ctx

        gap_type = gap_record.get("gap_type", "topic_missing")
        suggestions = await self._analyze_gap(query, gap_type)

        ctx["suggested_sources"] = suggestions
        ctx["refined_gap_type"] = gap_type
        logger.info(
            "GapAnalyzer: %d suggestions for gap_type=%s",
            len(suggestions),
            gap_type,
        )
        return ctx

    async def _analyze_gap(self, query: str, gap_type: str) -> list[dict[str, Any]]:
        """Use LLM to suggest sources. Falls back to empty on failure."""
        try:
            from src.shared.llm import acompletion

            prompt = (
                f"A document QA system could not answer this question adequately.\n"
                f"Question: {query}\n"
                f"Gap type: {gap_type}\n\n"
                f"Suggest 2-3 types of documents or sources "
                f"that would help answer this question. "
                f"For each, provide a title and brief description. "
                f"Return as a JSON array of objects with "
                f"'title', 'description', 'source_type' fields."
            )
            response = await acompletion(
                model="haiku",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=512,
                temperature=0.3,
            )
            content = response.choices[0].message.content

            import json

            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return [
                    {
                        "title": "Manual review needed",
                        "description": content[:200],
                        "source_type": "unknown",
                    }
                ]
        except Exception:
            logger.exception("Gap analysis LLM call failed")
            return []
