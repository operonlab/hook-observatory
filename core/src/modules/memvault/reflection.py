"""G5: Memory reflection — extract invariants and derived insights from session memories.

Adapted from memory-lancedb-pro's reflection system.
At session end, analyze stored memories to extract:
- Invariants: stable behavioral patterns that persist across sessions
- Derived: higher-order insights synthesized from multiple memories
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass
class ReflectionResult:
    invariants: list[str] = field(default_factory=list)
    derived: list[str] = field(default_factory=list)
    session_id: str = ""
    reflected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    block_count: int = 0


# --- Pattern-based extraction (no LLM dependency) ---

_PREFERENCE_PATTERN = re.compile(
    r"(偏好|喜歡|prefer|always|never|一律|禁止|必須|鐵律|must|should|shouldn'?t)",
    re.IGNORECASE,
)
_WORKFLOW_PATTERN = re.compile(
    r"(流程|步驟|pipeline|workflow|先.*再.*然後|step\s*\d|phase\s*\d)",
    re.IGNORECASE,
)
_DECISION_PATTERN = re.compile(
    r"(決定|決策|decided|chose|選擇|採用|rejected|不採用|棄用)",
    re.IGNORECASE,
)
_LESSON_PATTERN = re.compile(
    r"(學到|教訓|踩坑|lesson|learned|gotcha|注意|小心|caveat|pitfall)",
    re.IGNORECASE,
)
_RULE_PATTERN = re.compile(
    r"(規則|慣例|convention|pattern|原則|principle|策略|strategy)",
    re.IGNORECASE,
)


def _classify_content(content: str) -> str | None:
    """Classify content into invariant/derived categories."""
    if _PREFERENCE_PATTERN.search(content):
        return "invariant"
    if _RULE_PATTERN.search(content):
        return "invariant"
    if _WORKFLOW_PATTERN.search(content):
        return "derived"
    if _DECISION_PATTERN.search(content):
        return "derived"
    if _LESSON_PATTERN.search(content):
        return "derived"
    return None


def _extract_key_sentence(content: str) -> str:
    """Extract the most informative sentence from content."""
    # Split by Chinese/English sentence boundaries
    sentences = re.split(r"[。.!\uff01?\n]", content)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
    if not sentences:
        return content[:200]

    # Prefer sentences with pattern markers
    for s in sentences:
        if _PREFERENCE_PATTERN.search(s) or _RULE_PATTERN.search(s):
            return s
    for s in sentences:
        if _DECISION_PATTERN.search(s) or _LESSON_PATTERN.search(s):
            return s

    # Fallback: longest sentence (most informative)
    return max(sentences, key=len)


def reflect_on_session(
    blocks: list[dict],
    session_id: str = "",
) -> ReflectionResult:
    """Analyze session memories and extract invariants + derived insights.

    Args:
        blocks: List of dicts with at least 'content' and optionally 'block_type', 'tags'.
        session_id: Optional session identifier.

    Returns:
        ReflectionResult with extracted invariants and derived.
    """
    result = ReflectionResult(session_id=session_id, block_count=len(blocks))

    if not blocks:
        return result

    seen_invariants: set[str] = set()
    seen_derived: set[str] = set()

    for block in blocks:
        content = block.get("content", "")
        if not content or len(content) < 20:
            continue

        category = _classify_content(content)
        if not category:
            continue

        key_sentence = _extract_key_sentence(content)

        # Dedup by key sentence similarity (simple word overlap)
        key_words = frozenset(key_sentence.lower().split()[:10])

        if category == "invariant":
            if key_words not in seen_invariants:
                seen_invariants.add(key_words)
                result.invariants.append(key_sentence)
        elif category == "derived":
            if key_words not in seen_derived:
                seen_derived.add(key_words)
                result.derived.append(key_sentence)

    # Cap at reasonable limits
    result.invariants = result.invariants[:10]
    result.derived = result.derived[:10]

    return result


def format_reflection_for_injection(reflection: ReflectionResult) -> str:
    """Format reflection result for injection into future session context."""
    parts = []

    if reflection.invariants:
        parts.append("## Behavioral Invariants")
        for inv in reflection.invariants:
            parts.append(f"- {inv}")

    if reflection.derived:
        parts.append("## Derived Insights")
        for d in reflection.derived:
            parts.append(f"- {d}")

    return "\n".join(parts)
