"""Groundedness verification — three-tier anti-hallucination for DocVault QA.

Tier 1: Span validation (pure Python, ~0ms) — check answer claims exist in chunks
Tier 2: NLI claim verification (LLM-based, ~50ms) — verify entailment per claim
Tier 3: Self-consistency (multi-generation, ~300ms) — majority vote, toggle-controlled
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from pydantic_ai import Agent

from ..llm_config import get_model
from ..llm_models import GroundednessResult, SynthResult

logger = logging.getLogger(__name__)

# ── Tier 2 & 3 toggles (off by default — extra LLM calls add latency) ──
NLI_VERIFICATION_ENABLED = os.environ.get("DOCVAULT_NLI_VERIFY", "0") == "1"
SELF_CONSISTENCY_ENABLED = os.environ.get("DOCVAULT_SELF_CONSISTENCY", "0") == "1"

# ── Tier 1: Span Validation ──

# Regex to extract numbers with units (e.g., "5,000 words", "1024 characters", "30 minutes")
_NUMBER_PATTERN = re.compile(
    r"\b(\d[\d,]*\.?\d*)\s*(words?|characters?|chars?|bytes?|pages?|minutes?|hours?|"
    r"seconds?|tokens?|items?|steps?|days?|weeks?|months?|years?|"
    r"KB|MB|GB|TB|%)\b",
    re.IGNORECASE,
)


def validate_spans(answer: str, chunks: list[dict[str, Any]]) -> list[str]:
    """Tier 1: Check that specific numbers/measurements in the answer exist in chunks.

    Returns list of flagged claims (numbers found in answer but not in any chunk).
    """
    if not answer or not chunks:
        return []

    # Combine all chunk text
    all_chunk_text = " ".join(c.get("content", "") for c in chunks).lower()

    flagged: list[str] = []
    for match in _NUMBER_PATTERN.finditer(answer):
        number_str = match.group(1).replace(",", "")
        full_match = match.group(0)

        # Check if the exact number appears in any chunk
        # Also check without commas
        if number_str not in all_chunk_text and match.group(1) not in all_chunk_text:
            flagged.append(full_match)
            logger.warning(
                "Groundedness T1: number '%s' not found in any evidence chunk",
                full_match,
            )

    return flagged


# ── Tier 2: NLI Claim Verification ──

_GROUNDEDNESS_PROMPT = """\
You are a fact-checking assistant. Given an ANSWER and numbered EVIDENCE chunks, \
verify each factual claim in the answer.

For each claim that contains a specific fact (number, name, definition, process step):
1. Check if the EXACT fact exists in the evidence chunks.
2. If the fact is a PARAPHRASE of evidence content, mark as supported.
3. If the fact CANNOT be traced to any evidence chunk, mark as NOT supported.

Focus on:
- Specific numbers, measurements, limits (e.g., "5000 words", "3 types")
- Named entities, tool names, API names
- Process steps or sequences
- Definitions or categorizations

Do NOT flag:
- General transitional phrases ("The document describes...")
- Obvious inferences from directly stated facts
- The question itself being restated

Output JSON with:
- claims: list of {claim, supported, chunk_id (if supported), explanation}
- overall_grounded: true if ALL factual claims are supported
- flagged_claims: list of unsupported claim texts
"""

_groundedness_agent = Agent(
    output_type=GroundednessResult,
    system_prompt=_GROUNDEDNESS_PROMPT,
    retries=1,
)


async def verify_claims(
    answer: str,
    chunks: list[dict[str, Any]],
) -> GroundednessResult:
    """Tier 2: Use LLM to verify each claim in the answer against evidence chunks.

    Returns GroundednessResult with per-claim verdicts.
    """
    if not NLI_VERIFICATION_ENABLED:
        return GroundednessResult()

    if not answer.strip() or not chunks:
        return GroundednessResult()

    # Build verification input
    chunk_text_parts = []
    for i, chunk in enumerate(chunks, 1):
        content = chunk.get("content", "")[:3000]
        chunk_text_parts.append(f"[{i}]: {content}")
    chunks_str = "\n\n".join(chunk_text_parts)

    user_msg = f"ANSWER:\n{answer}\n\nEVIDENCE CHUNKS:\n{chunks_str}"

    try:
        model = await get_model()
        result = await _groundedness_agent.run(
            user_msg,
            model=model,
            model_settings={"temperature": 0.0},
        )
        return result.output
    except Exception:
        logger.warning("Groundedness T2: verification failed, skipping", exc_info=True)
        return GroundednessResult()


# ── Tier 3: Self-Consistency ──


async def self_consistency_check(
    synth_agent: Agent,
    user_msg: str,
    chunks: list[dict[str, Any]],
    primary_result: SynthResult,
    n_samples: int = 2,
) -> SynthResult:
    """Tier 3: Generate N additional answers and vote on factual consistency.

    Compares key facts (numbers, specific terms) across all answers.
    If the primary answer's facts are contradicted by majority, adjust answer.

    Args:
        synth_agent: The synthesis PydanticAI agent.
        user_msg: The formatted question + evidence message.
        chunks: Evidence chunks for context.
        primary_result: The initial SynthResult to verify.
        n_samples: Number of additional generations (default 2 → total 3).

    Returns:
        SynthResult — original if consistent, or adjusted if majority disagrees.
    """
    if not SELF_CONSISTENCY_ENABLED:
        return primary_result

    if not primary_result.answer:
        return primary_result

    model = await get_model()

    # Generate N additional answers in parallel with higher temperature for diversity
    async def _generate_one() -> SynthResult | None:
        try:
            result = await synth_agent.run(
                user_msg,
                model=model,
                model_settings={"temperature": 0.4},
            )
            return result.output
        except Exception:
            return None

    secondary_results = await asyncio.gather(*[_generate_one() for _ in range(n_samples)])
    valid_results = [r for r in secondary_results if r and r.answer]

    if not valid_results:
        logger.debug("Groundedness T3: no valid secondary results, keeping primary")
        return primary_result

    # Extract numbers from all answers for comparison
    all_answers = [primary_result, *valid_results]
    number_votes: dict[str, list[str]] = {}  # number_with_unit → [answer_index, ...]

    for idx, result in enumerate(all_answers):
        if not result.answer:
            continue
        for match in _NUMBER_PATTERN.finditer(result.answer):
            key = f"{match.group(1).replace(',', '')}_{match.group(2).lower()}"
            number_votes.setdefault(key, []).append(str(idx))

    # Check if primary answer's numbers are supported by majority
    primary_numbers = set()
    if primary_result.answer:
        for match in _NUMBER_PATTERN.finditer(primary_result.answer):
            key = f"{match.group(1).replace(',', '')}_{match.group(2).lower()}"
            primary_numbers.add(key)

    contested_numbers = []
    for num_key in primary_numbers:
        votes = number_votes.get(num_key, [])
        # If primary is the only one with this number, it might be hallucinated
        if len(votes) <= 1 and len(all_answers) >= 3:
            contested_numbers.append(num_key)

    if contested_numbers:
        logger.warning(
            "Groundedness T3: contested numbers in primary: %s",
            contested_numbers,
        )
        # Pick the answer with highest agreement on numbers
        best_idx = 0
        best_agreement = 0
        for idx, result in enumerate(all_answers):
            if not result.answer:
                continue
            result_nums = set()
            for match in _NUMBER_PATTERN.finditer(result.answer):
                key = f"{match.group(1).replace(',', '')}_{match.group(2).lower()}"
                result_nums.add(key)
            # Count how many of this answer's numbers appear in other answers
            agreement = sum(1 for n in result_nums if len(number_votes.get(n, [])) > 1)
            if agreement > best_agreement:
                best_agreement = agreement
                best_idx = idx

        if best_idx != 0:
            logger.info(
                "Groundedness T3: replacing primary (idx=0) with idx=%d (better agreement)",
                best_idx,
            )
            return all_answers[best_idx]

    return primary_result
