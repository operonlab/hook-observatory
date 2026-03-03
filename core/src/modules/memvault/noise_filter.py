"""Dual-direction noise filter for memvault.

Capture-side: prevents noisy content from being stored.
Retrieval-side: filters noise from search results.
Shared logic for both directions.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# --- Greeting patterns ---

_GREETING_PATTERNS_EN = re.compile(
    r"^(hi|hello|hey|howdy|yo|sup|greetings|good\s*(morning|afternoon|evening|night))"
    r"[\s!.,]*$",
    re.IGNORECASE,
)
_GREETING_PATTERNS_CJK = re.compile(
    r"^(你好|嗨|哈囉|早安|午安|晚安|哈嘍|嘿)[\s!.,、。\uff01]*$",
)

# --- Agent refusal patterns ---

_REFUSAL_PATTERNS = re.compile(
    r"(I cannot|I can't|I'm unable|I am unable|As an AI|As a language model|"
    r"I don't have the ability|I'm not able|"
    r"我無法|我不能|作為AI|作為一個語言模型|身為AI)",
    re.IGNORECASE,
)

# --- Heartbeat / meta patterns ---

_HEARTBEAT_PATTERNS = re.compile(
    r"^(HEARTBEAT|ping|pong|test|ok|ack|noop)$",
    re.IGNORECASE,
)

# --- Memory keywords that override greeting detection ---

_MEMORY_KEYWORDS = re.compile(
    r"(記得|之前|上次|remember|previously|earlier|last\s*time|recall|memory|memorize)",
    re.IGNORECASE,
)

QUARANTINE_TAG = "__quarantined__"


@dataclass
class NoiseVerdict:
    is_noise: bool
    reason: str | None = None
    confidence: float = 1.0


def check_noise(content: str) -> NoiseVerdict:
    """Shared noise detection -- used by both capture and retrieval paths."""
    stripped = content.strip()

    # Too short
    if len(stripped) < 10:
        # Allow heartbeat check to provide more specific reason
        if _HEARTBEAT_PATTERNS.match(stripped):
            return NoiseVerdict(is_noise=True, reason="heartbeat", confidence=1.0)
        return NoiseVerdict(is_noise=True, reason="too_short", confidence=1.0)

    # Too repetitive: >80% same character
    if stripped:
        most_common_count = max(stripped.count(c) for c in set(stripped))
        if most_common_count / len(stripped) > 0.8:
            return NoiseVerdict(is_noise=True, reason="repetitive", confidence=0.9)

    # Check for memory keywords — if present, never classify as noise
    if _MEMORY_KEYWORDS.search(stripped):
        return NoiseVerdict(is_noise=False)

    # Greetings (but not if contains question mark)
    if "?" not in stripped and "\uff1f" not in stripped:
        if _GREETING_PATTERNS_EN.match(stripped) or _GREETING_PATTERNS_CJK.match(stripped):
            return NoiseVerdict(is_noise=True, reason="greeting", confidence=0.9)

    # Agent refusal
    if _REFUSAL_PATTERNS.search(stripped):
        return NoiseVerdict(is_noise=True, reason="agent_refusal", confidence=0.85)

    return NoiseVerdict(is_noise=False)


def filter_results(
    results: list[Any],
    key_fn: Callable[[Any], str] | None = None,
) -> tuple[list[Any], int]:
    """Filter noise from search results.

    Args:
        results: List of result objects.
        key_fn: Function to extract content string from a result.
                Defaults to accessing result.block.content for SemanticSearchResult.

    Returns:
        (clean_results, filtered_count)
    """
    if key_fn is None:

        def key_fn(r: Any) -> str:
            return r.block.content

    clean = []
    filtered = 0
    for r in results:
        content = key_fn(r)
        verdict = check_noise(content)
        if verdict.is_noise:
            filtered += 1
        else:
            clean.append(r)
    return clean, filtered
