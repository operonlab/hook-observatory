"""QueryExpandOp — expand a single query into multiple sub-queries for broader recall.

Uses a fast LLM to decompose the user's question into 2-3 diverse search queries
that cover different angles, synonyms, and related sections of the document.

Operator protocol:
  input_keys: ("query",)
  output_keys: ("expanded_queries",)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_EXPAND_PROMPT = """\
Generate 3 diverse search queries to find ALL relevant document sections. \
Each query MUST target a DIFFERENT angle.

EXAMPLES:

Q: "best practices for writing SKILL.md descriptions"
→ ["SKILL.md description field frontmatter requirements", \
"writing instructions good and bad examples formatting guidelines", \
"checklist before uploading skill quality validation"]

Q: "how to handle errors in MCP connections"
→ ["MCP connection error handling troubleshooting", \
"common MCP issues retry reconnect", \
"debugging checklist MCP server status"]

Q: "what testing approach should I use"
→ ["testing methodology skill validation", \
"quantitative qualitative metrics measurement", \
"iteration feedback improvement cycle"]

Return ONLY a JSON array of 3 strings. No explanation.
"""


async def expand_query(
    question: str,
    litellm_base: str = "http://localhost:4000/v1",
    litellm_key: str = "sk-litellm-local-dev",
    request_timeout: float = 10.0,
) -> list[str]:
    """Expand a question into multiple search queries via LLM."""
    # Always include the original query
    queries = [question]

    try:
        # Resolve available model
        from .cited_answer import _resolve_model

        model = _resolve_model()

        async with httpx.AsyncClient(timeout=request_timeout) as client:
            resp = await client.post(
                f"{litellm_base}/chat/completions",
                headers={"Authorization": f"Bearer {litellm_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _EXPAND_PROMPT},
                        {"role": "user", "content": question},
                    ],
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()

        content = resp.json()["choices"][0]["message"]["content"].strip()

        # Parse JSON array from response
        if content.startswith("["):
            expanded = json.loads(content)
        else:
            # Try to extract JSON from markdown code block
            import re

            match = re.search(r"\[.*\]", content, re.DOTALL)
            if match:
                expanded = json.loads(match.group())
            else:
                expanded = []

        if isinstance(expanded, list):
            for q in expanded:
                if isinstance(q, str) and q.strip() and q.strip() != question:
                    queries.append(q.strip())

    except Exception:
        logger.debug("QueryExpandOp: LLM expansion failed, using original query only")

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
