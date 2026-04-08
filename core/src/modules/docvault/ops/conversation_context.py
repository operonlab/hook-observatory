"""ConversationContextOp — Multi-turn QA with query rewriting.

Toggle: DOCVAULT_CONVERSATION=1 (off by default).
Position: Pipeline Step 0.5 (after cache lookup, before IntentRouter).

Redis structure:
- Key: docvault:conv:{session_id}
- Type: Sorted Set (score = timestamp)
- Value: JSON {"turn": N, "question": "...", "answer": "...", "timestamp": "..."}
- TTL: configurable (default 1800s = 30 min)
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

from pydantic_ai import Agent

from ..llm_config import get_model
from ..llm_models import ConversationRewriteResult

logger = logging.getLogger(__name__)

CONVERSATION_ENABLED = os.environ.get("DOCVAULT_CONVERSATION", "0") == "1"
MAX_TURNS = int(os.environ.get("DOCVAULT_CONV_MAX_TURNS", "5"))
TTL_MINUTES = int(os.environ.get("DOCVAULT_CONV_TTL_MINUTES", "30"))
TOKEN_BUDGET = int(os.environ.get("DOCVAULT_CONV_TOKEN_BUDGET", "2000"))

_REWRITE_PROMPT = """\
You are a query rewriter for a document QA system. Given the conversation history \
and the current question, rewrite the current question to be self-contained and \
unambiguous, resolving any coreferences or omissions.

Rules:
- If the current question references something from history (pronouns, "it", "that", \
partial references), resolve it to the full term.
- If the current question is already self-contained, return it as-is.
- Keep the rewritten question concise and natural.
- Preserve the ORIGINAL LANGUAGE of the question.
- Set needs_context=false if the question is already self-contained.
- List which turn numbers you referenced in references_used.

Example:
History: [Turn 1] Q: "What burgers do you have?" A: "We have chicken, pork, beef, fish burgers"
Current: "I want 2 chicken and 3 pork"
Rewrite: "I want 2 chicken burgers and 3 pork burgers"
"""

_rewrite_agent: Agent[None, ConversationRewriteResult] | None = None


def _get_agent() -> Agent[None, ConversationRewriteResult]:
    global _rewrite_agent
    if _rewrite_agent is None:
        _rewrite_agent = Agent(
            "openai:placeholder",
            output_type=ConversationRewriteResult,
            system_prompt=_REWRITE_PROMPT,
            retries=2,
        )
    return _rewrite_agent


async def _get_conversation_history(session_id: str) -> list[dict]:
    """Retrieve conversation history from Redis sorted set."""
    try:
        from src.shared.redis import get_redis

        r = get_redis()
        key = f"docvault:conv:{session_id}"
        # Get all entries sorted by score (timestamp)
        raw_entries = await r.zrangebyscore(key, "-inf", "+inf")
        history = []
        for entry in raw_entries:
            try:
                data = json.loads(entry)
                history.append(data)
            except (json.JSONDecodeError, TypeError):
                continue
        return history
    except Exception:
        logger.debug("Failed to retrieve conversation history")
        return []


async def store_conversation_turn(
    session_id: str,
    turn_number: int,
    question: str,
    answer: str,
) -> None:
    """Store a conversation turn in Redis."""
    if not session_id or not CONVERSATION_ENABLED:
        return

    try:
        from src.shared.redis import get_redis

        r = get_redis()
        key = f"docvault:conv:{session_id}"
        turn_data = json.dumps(
            {
                "turn": turn_number,
                "question": question,
                "answer": answer[:500],
                "timestamp": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
        )
        await r.zadd(key, {turn_data: time.time()})
        await r.expire(key, TTL_MINUTES * 60)
    except Exception:
        logger.debug("Failed to store conversation turn")


def _trim_history(
    history: list[dict],
    current_time: float,
) -> list[dict]:
    """Apply four-dimension trimming to conversation history."""
    if not history:
        return []

    # 1. Count limit: last N turns
    trimmed = history[-MAX_TURNS:]

    # 2. Time limit: within TTL
    cutoff_ts = datetime.now(UTC).timestamp() - (TTL_MINUTES * 60)
    trimmed = [
        h
        for h in trimmed
        if _parse_timestamp(h.get("timestamp", "")) > cutoff_ts
    ]

    # 3. Token budget: truncate oldest if over budget
    total_tokens = 0
    budget_trimmed = []
    for h in reversed(trimmed):
        turn_tokens = len(h.get("question", "")) + len(h.get("answer", ""))
        # Rough estimate: 1 char ≈ 0.5 tokens for mixed CJK/EN
        est_tokens = turn_tokens // 2
        if total_tokens + est_tokens > TOKEN_BUDGET:
            break
        total_tokens += est_tokens
        budget_trimmed.insert(0, h)

    return budget_trimmed


def _parse_timestamp(ts_str: str) -> float:
    """Parse ISO timestamp to Unix timestamp."""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, AttributeError):
        return 0.0


class ConversationContextOp:
    """Resolve coreferences and enrich query with conversation context."""

    name = "ConversationContextOp"
    input_keys = ("query", "session_id", "space_id")
    output_keys = ("original_query", "rewritten_query", "conversation_history", "turn_number")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        session_id = ctx.get("session_id")

        if not CONVERSATION_ENABLED or not session_id:
            return ctx

        # Retrieve and trim history
        history = await _get_conversation_history(session_id)
        trimmed = _trim_history(history, time.time())

        turn_number = len(history) + 1
        ctx["turn_number"] = turn_number
        ctx["original_query"] = ctx.get("query", "")

        if not trimmed:
            # No history — first turn, no rewriting needed
            ctx["conversation_history"] = []
            ctx["rewritten_query"] = ctx.get("query", "")
            return ctx

        ctx["conversation_history"] = trimmed

        # Build history text for rewriting
        history_text = "\n".join(
            f"[Turn {h.get('turn', '?')}] Q: {h.get('question', '')} "
            f"A: {h.get('answer', '')[:200]}"
            for h in trimmed
        )

        current_query = ctx.get("query", "")

        try:
            agent = _get_agent()
            model = await get_model()
            result = await agent.run(
                f"Conversation history:\n{history_text}\n\n"
                f"Current question: {current_query}",
                model=model,
            )
            rewritten = result.output.rewritten_query
            ctx["rewritten_query"] = rewritten

            if rewritten != current_query:
                logger.info(
                    "Query rewritten: '%s' → '%s'",
                    current_query[:60],
                    rewritten[:60],
                )
                # Replace the query in ctx so downstream ops use the rewritten version
                ctx["query"] = rewritten

        except Exception:
            logger.debug("Query rewriting failed, using original")
            ctx["rewritten_query"] = current_query

        return ctx
