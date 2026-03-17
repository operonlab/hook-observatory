"""G5: Memory reflection — extract invariants and derived insights from session memories.

Adapted from memory-lancedb-pro's reflection system.
At session end, analyze stored memories to extract:
- Invariants: stable behavioral patterns that persist across sessions
- Derived: higher-order insights synthesized from multiple memories
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class ReflectionResult:
    invariants: list[str] = field(default_factory=list)
    derived: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)  # factual fixes / retractions
    session_id: str = ""
    reflected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    block_count: int = 0


# --- Pattern-based extraction (no LLM dependency) ---

# Preferences: what the user/system always/never does, favors, or avoids
_PREFERENCE_PATTERN = re.compile(
    r"(偏好|喜歡|我比較喜歡|我覺得.*比較好|prefer|rather|instead of|always|never"
    r"|一律|禁止|必須|鐵律|must|should|shouldn'?t)",
    re.IGNORECASE,
)

# Workflows: step-by-step processes, migration paths, new approaches
_WORKFLOW_PATTERN = re.compile(
    r"(流程|步驟|流程改成|改用|從.*改成|新做法|pipeline|workflow"
    r"|switch\s+to|migrate\s+to|先.*再.*然後|step\s*\d|phase\s*\d)",
    re.IGNORECASE,
)

# Decisions: confirmed choices, rejected options, finalized direction
_DECISION_PATTERN = re.compile(
    r"(決定|決策|決定了|拍板|定案|最後選|decided|chose|confirmed|we'?ll\s+go\s+with"
    r"|選擇|採用|rejected|不採用|棄用)",
    re.IGNORECASE,
)

# Lessons: things learned the hard way, caveats, surprises
_LESSON_PATTERN = re.compile(
    r"(學到|教訓|踩坑|才知道|原來|注意|小心"
    r"|lesson|learned|gotcha|turns?\s+out|caveat|pitfall)",
    re.IGNORECASE,
)

# Rules: conventions, principles, strategies — stable behavioral patterns
_RULE_PATTERN = re.compile(
    r"(規則|慣例|以後|鐵律|convention|pattern|原則|principle|策略|strategy"
    r"|must\s+always|never\s+again|禁止|一定要)",
    re.IGNORECASE,
)

# Corrections/Updates: factual fixes, retractions, "actually it's X not Y"
_CORRECTION_PATTERN = re.compile(
    r"(不[是對]|搞錯|更正|其實是|correction|actually|wait.*wrong"
    r"|之前說錯|should\s+be|not.*but\s+rather)",
    re.IGNORECASE,
)


def _classify_content(content: str) -> str | None:
    """Classify content into invariant/derived/correction categories."""
    if _PREFERENCE_PATTERN.search(content):
        return "invariant"
    if _RULE_PATTERN.search(content):
        return "invariant"
    if _CORRECTION_PATTERN.search(content):
        return "correction"
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


async def apply_reflection_to_kg(
    db: AsyncSession,
    space_id: str,
    reflection_result: ReflectionResult,
    session_id: str = "",
) -> dict[str, int]:
    """Write reflection results back to the Knowledge Graph.

    - invariants → TripleService.batch_ingest (predicate: has_behavioral_invariant)
    - derived    → TripleService.batch_ingest (predicate: yielded_insight)
    - corrections → mark matching triples invalid_at (predicate: contradicts)

    All operations are fail-safe (try/except each section).

    Returns:
        {"triples_created": int, "triples_invalidated": int}
    """
    from .kg_schemas import TripleBatchCreate, TripleCreate
    from .kg_services import triple_service

    triples_created = 0
    triples_invalidated = 0

    ref_session_id = session_id or reflection_result.session_id
    ingest_session = f"reflection:{ref_session_id}" if ref_session_id else "reflection:unknown"

    # --- Invariants: user has_behavioral_invariant <text> ---
    if reflection_result.invariants:
        try:
            batch = TripleBatchCreate(
                session_id=ingest_session,
                triples=[
                    TripleCreate(
                        subject="user",
                        predicate="has_behavioral_invariant",
                        object=inv[:500],
                        source_session=ingest_session,
                    )
                    for inv in reflection_result.invariants
                ],
            )
            created = await triple_service.batch_ingest(db, space_id, batch)
            triples_created += len(created)
            logger.debug(
                "reflection.kg_writeback.invariants created=%d session=%s",
                len(created),
                ingest_session,
            )
        except Exception:
            logger.warning(
                "reflection.kg_writeback.invariants failed",
                exc_info=True,
            )

    # --- Derived: session:{id} yielded_insight <text> ---
    if reflection_result.derived:
        try:
            subject = f"session:{ref_session_id}" if ref_session_id else "session:unknown"
            batch = TripleBatchCreate(
                session_id=ingest_session,
                triples=[
                    TripleCreate(
                        subject=subject,
                        predicate="yielded_insight",
                        object=d[:500],
                        source_session=ingest_session,
                    )
                    for d in reflection_result.derived
                ],
            )
            created = await triple_service.batch_ingest(db, space_id, batch)
            triples_created += len(created)
            logger.debug(
                "reflection.kg_writeback.derived created=%d session=%s",
                len(created),
                ingest_session,
            )
        except Exception:
            logger.warning(
                "reflection.kg_writeback.derived failed",
                exc_info=True,
            )

    # --- Corrections: record contradiction triples (Phase 1: mark, not auto-invalidate) ---
    if reflection_result.corrections:
        try:
            batch = TripleBatchCreate(
                session_id=ingest_session,
                triples=[
                    TripleCreate(
                        subject="user",
                        predicate="contradicts",
                        object=c[:500],
                        source_session=ingest_session,
                    )
                    for c in reflection_result.corrections
                ],
            )
            created = await triple_service.batch_ingest(db, space_id, batch)
            triples_created += len(created)
            logger.debug(
                "reflection.kg_writeback.corrections created=%d session=%s",
                len(created),
                ingest_session,
            )
        except Exception:
            logger.warning(
                "reflection.kg_writeback.corrections failed",
                exc_info=True,
            )

    return {"triples_created": triples_created, "triples_invalidated": triples_invalidated}
