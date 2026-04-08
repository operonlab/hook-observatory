"""QueryExpandOp — expand a single query into multiple sub-queries for broader recall.

Uses a fast LLM to decompose the user's question into 2-3 diverse search queries
that cover different angles, synonyms, and related sections of the document.

Operator protocol:
  input_keys: ("query",)
  output_keys: ("expanded_queries",)
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent

from ..llm_config import get_model
from ..llm_models import ExpandedQueries

logger = logging.getLogger(__name__)

_EXPAND_PROMPT = """\
Generate 3 diverse search queries to find ALL relevant document sections. \
Each query MUST target a DIFFERENT angle.

EXAMPLES:

Q: "best practices for writing SKILL.md descriptions"
→ {"queries": ["SKILL.md description field frontmatter requirements", \
"writing instructions good and bad examples formatting guidelines", \
"checklist before uploading skill quality validation"]}

Q: "how to handle errors in MCP connections"
→ {"queries": ["MCP connection error handling troubleshooting", \
"common MCP issues retry reconnect", \
"debugging checklist MCP server status"]}

Q: "what testing approach should I use"
→ {"queries": ["testing methodology skill validation", \
"quantitative qualitative metrics measurement", \
"iteration feedback improvement cycle"]}

Return ONLY a JSON object with a "queries" field containing an array of 3 strings. \
No explanation.
"""

_expand_agent = Agent(
    output_type=ExpandedQueries,
    system_prompt=_EXPAND_PROMPT,
    retries=2,
)


async def expand_query(question: str) -> list[str]:
    """Expand a question into multiple search queries via LLM."""
    queries = [question]

    try:
        model = await get_model()
        result = await _expand_agent.run(
            question,
            model=model,
            model_settings={"temperature": 0.3, "timeout": 10},
        )
        for q in result.output.queries:
            if q.strip() and q.strip() != question:
                queries.append(q.strip())

    except Exception:
        logger.warning(
            "QueryExpandOp: LLM expansion failed, using original query only",
            exc_info=True,
        )

    return queries[:4]  # Cap at 4 queries max


class QueryExpandOp:
    """Expand query into sub-queries for multi-angle search.

    Operator protocol:
      input_keys: ("query",)
      output_keys: ("expanded_queries",)
    """

    @property
    def name(self) -> str:
        return "query_expand"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("query",)

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("expanded_queries",)

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        query: str = ctx.get("query", "")
        queries = await expand_query(query)
        ctx["expanded_queries"] = queries

        logger.info(
            "QueryExpandOp: %r → %d sub-queries",
            query[:60],
            len(queries),
        )
        return ctx
