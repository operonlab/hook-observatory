"""Memory Conflict Resolver — LLM-driven three-way arbitration.

Based on ActMem (arXiv:2603.00026) + Memory-R1 research patterns.

When new content is semantically similar to existing memory but potentially
contradictory, use LLM to determine the right action.

Three decisions:
  MERGE: Content is complementary — combine them
  SUPERSEDE: New content replaces old (temporal update / more authoritative)
  COEXIST: Different perspectives on same topic — keep both

This module is pure — it does NOT modify dedup.py. Callers in dedup or
services layer invoke ``resolve_conflict()`` when similarity is high and
semantic arbitration is desired.
"""

import json
import logging
from dataclasses import dataclass
from enum import StrEnum

import httpx

logger = logging.getLogger(__name__)

# oMLX local LLM inference endpoint
_OMLX_URL = "http://localhost:8000/v1/chat/completions"
_LLM_TIMEOUT = 10  # seconds

# Similarity thresholds that trigger conflict arbitration
CONFLICT_SIMILARITY_THRESHOLD = 0.85
HIGH_SIMILARITY_THRESHOLD = 0.95


class ConflictDecision(StrEnum):
    MERGE = "merge"  # Complementary info → combine
    SUPERSEDE = "supersede"  # New replaces old (temporal update)
    COEXIST = "coexist"  # Different perspectives → keep both


@dataclass
class ConflictResult:
    decision: ConflictDecision
    confidence: float  # 0-1, how confident the LLM is
    reason: str
    merged_content: str | None = None  # Only populated for MERGE decision


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_conflict_prompt(new_content: str, existing_content: str, block_type: str) -> str:
    """Build the system + user prompt for LLM conflict arbitration.

    The LLM receives both memory snippets and the block_type context,
    and must return a JSON object with decision, confidence, reason, and
    optionally merged_content.
    """
    system_prompt = (
        "You are a memory conflict arbitrator for a personal knowledge management system. "
        "Your task is to compare two memory fragments and decide how to handle them.\n\n"
        "Possible decisions:\n"
        '- "merge": The memories are complementary — they cover the same topic from the same angle '
        "and combining them produces a richer, non-redundant record.\n"
        '- "supersede": The new memory is an update, correction, or more authoritative version '
        "of the existing one. The existing memory should be replaced.\n"
        '- "coexist": The memories represent genuinely different perspectives, time periods, or '
        "contexts. Both are independently valuable and should be kept as separate entries.\n\n"
        "Return ONLY valid JSON with this schema (no markdown fences, no extra text):\n"
        '{"decision": "merge|supersede|coexist", '
        '"confidence": <float 0-1>, '
        '"reason": "<one sentence explanation>", '
        '"merged_content": "<combined text, only for merge decision, else null>"}'
    )

    user_prompt = (
        f"Block type: {block_type}\n\n"
        f"EXISTING memory:\n{existing_content}\n\n"
        f"NEW memory:\n{new_content}\n\n"
        "Analyze the relationship between these two memories and return the JSON decision."
    )

    return json.dumps({"system": system_prompt, "user": user_prompt})


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


async def _call_llm(new_content: str, existing_content: str, block_type: str) -> ConflictResult:
    """Call oMLX local LLM and parse the conflict resolution response.

    Raises httpx.HTTPError or json.JSONDecodeError on failure — callers
    should catch and fall back to the heuristic.
    """
    system_prompt = (
        "You are a memory conflict arbitrator for a personal knowledge management system. "
        "Your task is to compare two memory fragments and decide how to handle them.\n\n"
        "Possible decisions:\n"
        '- "merge": The memories are complementary — they cover the same topic from the same '
        "angle and combining them produces a richer, non-redundant record.\n"
        '- "supersede": The new memory is an update, correction, or more authoritative version '
        "of the existing one. The existing memory should be replaced.\n"
        '- "coexist": The memories represent genuinely different perspectives, time periods, or '
        "contexts. Both are independently valuable and should be kept as separate entries.\n\n"
        "Return ONLY valid JSON with this schema (no markdown fences, no extra text):\n"
        '{"decision": "merge|supersede|coexist", '
        '"confidence": <float 0-1>, '
        '"reason": "<one sentence explanation>", '
        '"merged_content": "<combined text, only for merge decision, else null>"}'
    )

    user_message = (
        f"Block type: {block_type}\n\n"
        f"EXISTING memory:\n{existing_content}\n\n"
        f"NEW memory:\n{new_content}\n\n"
        "Analyze the relationship between these two memories and return the JSON decision."
    )

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.1,  # Low temperature for consistent arbitration
        "max_tokens": 256,
    }

    async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
        resp = await client.post(_OMLX_URL, json=payload)
        resp.raise_for_status()

    from src.shared.llm_json import parse_llm_json

    data = resp.json()
    raw_text: str = data["choices"][0]["message"]["content"]

    parsed = parse_llm_json(raw_text)
    if not isinstance(parsed, dict):
        raise ValueError(f"LLM returned non-dict response: {raw_text[:100]}")

    decision_str = str(parsed.get("decision", "coexist")).lower()
    try:
        decision = ConflictDecision(decision_str)
    except ValueError:
        logger.warning("LLM returned unknown decision %r — defaulting to coexist", decision_str)
        decision = ConflictDecision.COEXIST

    confidence = float(parsed.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))  # clamp to [0, 1]
    reason = str(parsed.get("reason", "LLM arbitration"))
    merged_content: str | None = (
        parsed.get("merged_content") if decision == ConflictDecision.MERGE else None
    )

    return ConflictResult(
        decision=decision,
        confidence=confidence,
        reason=reason,
        merged_content=merged_content or None,
    )


# ---------------------------------------------------------------------------
# Heuristic fallback
# ---------------------------------------------------------------------------


def _simple_conflict_heuristic(
    new_content: str,
    existing_content: str,
    similarity: float,
) -> ConflictResult:
    """Fallback when LLM is unavailable.

    Logic:
    - Very high similarity (>0.95) + high word overlap → MERGE (almost same content)
    - High similarity (0.85-0.95) or low word overlap → COEXIST (different perspectives)
    """
    words_new = set(new_content.lower().split())
    words_existing = set(existing_content.lower().split())

    if not words_new or not words_existing:
        return ConflictResult(
            decision=ConflictDecision.COEXIST,
            confidence=0.5,
            reason="empty_content_fallback",
        )

    intersection = words_new & words_existing
    union = words_new | words_existing
    overlap = len(intersection) / len(union)

    if similarity > HIGH_SIMILARITY_THRESHOLD and overlap > 0.7:
        return ConflictResult(
            decision=ConflictDecision.MERGE,
            confidence=0.7,
            reason=f"heuristic_high_overlap (sim={similarity:.3f}, overlap={overlap:.2f})",
        )

    return ConflictResult(
        decision=ConflictDecision.COEXIST,
        confidence=0.6,
        reason=f"heuristic_coexist (sim={similarity:.3f}, overlap={overlap:.2f})",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def resolve_conflict(
    new_content: str,
    existing_content: str,
    existing_block_id: str,
    block_type: str = "knowledge",
    similarity: float = 0.0,
) -> ConflictResult:
    """Resolve a potential memory conflict using LLM arbitration.

    Intended to be called from the dedup layer when:
      - similarity > CONFLICT_SIMILARITY_THRESHOLD (0.85)
      - AND the preliminary decision is MERGE or SKIP

    Uses oMLX local LLM at port 8000 for arbitration.
    Falls back to ``_simple_conflict_heuristic`` if the LLM is unavailable
    or returns unparseable output.

    Args:
        new_content: The incoming memory content.
        existing_content: The content of the existing memory block.
        existing_block_id: ID of the existing block (for caller reference only).
        block_type: Memvault block type — knowledge | skill | attitude | general.
        similarity: Cosine similarity between the two embeddings (0-1).

    Returns:
        ConflictResult with decision, confidence, reason, and optional merged_content.
    """
    logger.debug(
        "resolve_conflict: block_id=%s type=%s sim=%.3f",
        existing_block_id,
        block_type,
        similarity,
    )

    try:
        result = await _call_llm(new_content, existing_content, block_type)
        logger.info(
            "conflict_resolved(llm): block_id=%s decision=%s confidence=%.2f reason=%r",
            existing_block_id,
            result.decision,
            result.confidence,
            result.reason,
        )
        return result

    except httpx.ConnectError:
        logger.warning(
            "oMLX unreachable — using heuristic for conflict resolution (block_id=%s)",
            existing_block_id,
        )
    except httpx.TimeoutException:
        logger.warning(
            "oMLX timed out after %ds — using heuristic (block_id=%s)",
            _LLM_TIMEOUT,
            existing_block_id,
        )
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "oMLX HTTP %d — using heuristic (block_id=%s)",
            exc.response.status_code,
            existing_block_id,
        )
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning(
            "LLM response parse error %s — using heuristic (block_id=%s)",
            exc,
            existing_block_id,
        )
    except Exception as exc:
        logger.exception(
            "Unexpected error in conflict resolution — using heuristic (block_id=%s): %s",
            existing_block_id,
            exc,
        )

    result = _simple_conflict_heuristic(new_content, existing_content, similarity)
    logger.info(
        "conflict_resolved(heuristic): block_id=%s decision=%s reason=%r",
        existing_block_id,
        result.decision,
        result.reason,
    )
    return result


# ---------------------------------------------------------------------------
# RLM-enhanced conflict resolution
# ---------------------------------------------------------------------------

_RLM_CONFIDENCE_THRESHOLD = 0.7  # Trigger RLM when Haiku confidence below this


def _run_rlm_conflict(new_content: str, existing_content: str, block_type: str) -> ConflictResult:
    """Run RLM conflict resolution synchronously (called via asyncio.to_thread).

    RLM recursively: (1) extracts claims from both blocks, (2) analyzes
    semantic relationship, (3) produces merged content if applicable.
    """
    from src.shared.rlm_engine import RLMConfig, RLMEngine

    config = RLMConfig(
        model="grok-4-fast",
        api_base="http://localhost:4000/v1",
        api_key="sk-litellm-local-dev",
        max_iterations=5,
        max_timeout_secs=60,
    )
    engine = RLMEngine(config)

    prompt = (
        "You are a memory conflict arbitrator. Two memory blocks may overlap, contradict, "
        "or complement each other.\n\n"
        "Your task:\n"
        "1. Extract distinct claims from EACH block\n"
        "2. Analyze the semantic relationship (complementary, contradictory, temporal update)\n"
        "3. Decide: merge / supersede / coexist\n"
        "4. If merge: produce combined content that preserves all non-redundant information\n\n"
        "Return ONLY valid JSON (no markdown fences):\n"
        '{"decision": "merge|supersede|coexist", '
        '"confidence": <float 0-1>, '
        '"reason": "<explanation>", '
        '"merged_content": "<combined text or null>"}'
    )

    context = (
        f"Block type: {block_type}\n\n"
        f"EXISTING memory:\n{existing_content}\n\n"
        f"NEW memory:\n{new_content}"
    )

    result = engine.completion(prompt=prompt, context=context)

    if result.status != "ok":
        raise RuntimeError(f"RLM returned status={result.status}")

    from src.shared.llm_json import parse_llm_json

    parsed = parse_llm_json(result.response)
    if not isinstance(parsed, dict):
        raise RuntimeError("RLM returned non-dict response")

    decision_str = str(parsed.get("decision", "coexist")).lower()
    try:
        decision = ConflictDecision(decision_str)
    except ValueError:
        decision = ConflictDecision.COEXIST

    confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
    reason = str(parsed.get("reason", "RLM arbitration"))
    merged_content: str | None = (
        parsed.get("merged_content") if decision == ConflictDecision.MERGE else None
    )

    return ConflictResult(
        decision=decision,
        confidence=confidence,
        reason=f"rlm: {reason}",
        merged_content=merged_content or None,
    )


async def resolve_conflict_rlm(
    new_content: str,
    existing_content: str,
    existing_block_id: str,
    block_type: str = "knowledge",
    similarity: float = 0.0,
) -> ConflictResult:
    """RLM-enhanced conflict resolution — escalates from Haiku when confidence < 0.7.

    Flow:
      1. Run standard resolve_conflict() (Haiku via oMLX)
      2. If confidence >= 0.7, return as-is
      3. If confidence < 0.7, escalate to RLM for deeper recursive analysis
      4. On RLM failure, return the original Haiku result

    Same signature as resolve_conflict() for drop-in use.
    """
    import asyncio

    # Step 1: Run standard Haiku resolution
    haiku_result = await resolve_conflict(
        new_content=new_content,
        existing_content=existing_content,
        existing_block_id=existing_block_id,
        block_type=block_type,
        similarity=similarity,
    )

    # Step 2: Gate — only escalate on low confidence
    if haiku_result.confidence >= _RLM_CONFIDENCE_THRESHOLD:
        logger.debug(
            "resolve_conflict_rlm: haiku conf=%.2f >= %.2f, keeping (block_id=%s)",
            haiku_result.confidence,
            _RLM_CONFIDENCE_THRESHOLD,
            existing_block_id,
        )
        return haiku_result

    # Step 3: Escalate to RLM
    logger.info(
        "resolve_conflict_rlm: haiku confidence=%.2f < %.2f, escalating to RLM (block_id=%s)",
        haiku_result.confidence,
        _RLM_CONFIDENCE_THRESHOLD,
        existing_block_id,
    )

    try:
        rlm_result = await asyncio.to_thread(
            _run_rlm_conflict, new_content, existing_content, block_type
        )
        logger.info(
            "conflict_resolved(rlm): block_id=%s decision=%s confidence=%.2f reason=%r",
            existing_block_id,
            rlm_result.decision,
            rlm_result.confidence,
            rlm_result.reason,
        )
        return rlm_result

    except Exception as exc:
        logger.warning(
            "RLM conflict resolution failed — using haiku result (block_id=%s): %s",
            existing_block_id,
            exc,
        )
        return haiku_result
