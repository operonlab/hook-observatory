"""AnswerJudgeOp — LLM-as-Judge for QA benchmark evaluation.

Replaces keyword matching with semantic evaluation using PydanticAI.
Toggle: DOCVAULT_ANSWER_JUDGE=1 (off by default).

NOT part of the live QA pipeline — used only in qa_benchmark.py.
"""

from __future__ import annotations

import logging
import os

from pydantic_ai import Agent

from ..llm_config import get_model
from ..llm_models import AnswerJudgeResult

logger = logging.getLogger(__name__)

ANSWER_JUDGE_ENABLED = os.environ.get("DOCVAULT_ANSWER_JUDGE", "0") == "1"

_JUDGE_PROMPT = """\
You are an expert QA evaluation judge for a RAG (Retrieval-Augmented Generation) system.

CRITICAL: The "Expected Answer" is the GROUND TRUTH from the actual document. \
Do NOT use your own world knowledge to judge whether the expected answer is correct. \
Treat it as absolute truth. Your ONLY job is to compare the Actual Answer against \
the Expected Answer.

Evaluate the actual answer on three dimensions:

1. **Relevance** (0-1): Does the actual answer address the question asked?
2. **Accuracy** (0-1): Does the actual answer contain the same facts, numbers, and claims \
as the expected answer? Pay special attention to exact numbers, percentages, and proper nouns.
3. **Completeness** (0-1): Does the actual answer cover all key points from the expected answer?

Rules:
- The expected answer is ALWAYS correct — never question it.
- For negative/refusal questions (where the expected answer indicates the information is \
NOT in the document), give high scores if the actual answer also correctly refuses or \
states the information is unavailable.
- Synonyms and paraphrases are acceptable (e.g., "1M tokens" = "1,000,000 tokens").
- Different formatting of the same number is acceptable (e.g., "$75" = "75 dollars").
- The overall score should be a weighted average: accuracy 0.4 + relevance 0.3 + completeness 0.3.
- Provide brief reasoning (1-2 sentences) explaining your judgment.
"""

_judge_agent: Agent[None, AnswerJudgeResult] | None = None


def _get_agent() -> Agent[None, AnswerJudgeResult]:
    global _judge_agent
    if _judge_agent is None:
        _judge_agent = Agent(
            "openai:placeholder",
            output_type=AnswerJudgeResult,
            system_prompt=_JUDGE_PROMPT,
            retries=2,
        )
    return _judge_agent


async def judge_answer(
    question: str,
    expected_answer: str,
    actual_answer: str,
    is_negative: bool = False,
) -> AnswerJudgeResult | None:
    """Evaluate an answer using LLM-as-Judge.

    Returns None if ANSWER_JUDGE_ENABLED is False.
    """
    if not ANSWER_JUDGE_ENABLED:
        return None

    agent = _get_agent()
    model = await get_model()

    negative_hint = (
        "\nNOTE: This is a NEGATIVE question — the expected answer indicates the information "
        "is NOT in the document. Score highly if the actual answer correctly refuses or states "
        "the information is unavailable."
        if is_negative
        else ""
    )

    user_msg = (
        f"Question: {question}\n\n"
        f"Expected Answer: {expected_answer}\n\n"
        f"Actual Answer: {actual_answer}"
        f"{negative_hint}"
    )

    try:
        result = await agent.run(user_msg, model=model)
        return result.output
    except Exception:
        logger.exception("AnswerJudgeOp failed")
        return None
