"""G5: Memory reflection — extract invariants and derived insights from session memories.

Adapted from memory-lancedb-pro's reflection system.
At session end, analyze stored memories to extract:
- Invariants: stable behavioral patterns that persist across sessions
- Derived: higher-order insights synthesized from multiple memories
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Pure functions delegated to shared G-R-C framework — re-exported for backwards compat.
from src.shared.grc import classify_content as _classify_content
from src.shared.grc import extract_key_sentence as _extract_key_sentence

__all__ = [
    "ReflectionResult",
    "_classify_content",
    "_extract_key_sentence",
    "format_reflection_for_injection",
    "reflect_on_session",
]

logger = logging.getLogger(__name__)


@dataclass
class ReflectionResult:
    invariants: list[str] = field(default_factory=list)
    derived: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)  # factual fixes / retractions
    session_id: str = ""
    reflected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    block_count: int = 0


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

    seen_invariants: set[frozenset] = set()
    seen_derived: set[frozenset] = set()
    seen_corrections: set[frozenset] = set()

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
        elif category == "correction":
            if key_words not in seen_corrections:
                seen_corrections.add(key_words)
                result.corrections.append(key_sentence)

    # Cap at reasonable limits
    result.invariants = result.invariants[:10]
    result.derived = result.derived[:10]
    result.corrections = result.corrections[:5]  # corrections are high-signal, keep fewer

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

    if reflection.corrections:
        parts.append("## Corrections / Updates")
        for c in reflection.corrections:
            parts.append(f"- {c}")

    return "\n".join(parts)
