"""G1+G8: Block-level deduplication — prevent memory bloat from duplicate content.

Adapted from memory-lancedb-pro's two-stage dedup (G1) and per-category dedup rules (G8):
Stage 1: Vector similarity pre-filter (fast, DB-level)
Stage 2: Content comparison decision (merge/skip/create) — now category-aware

G8: Per-category dedup behavior mapping:
  knowledge  → MERGE_IF_SIMILAR  (standard threshold 0.88)
  attitude   → ALWAYS_MERGE      (aggressive threshold 0.75, opinions/preferences consolidate)
  skill      → APPEND_ONLY       (skills are discrete, don't merge)
  general    → MERGE_IF_SIMILAR  (standard threshold 0.88)
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.qdrant_client import is_available as qdrant_available
from src.shared.qdrant_search import hybrid_search
from src.shared.search_types import SearchConfig

from .models import EMBEDDING_DIM, BlockEmbedding, MemoryBlock

logger = logging.getLogger(__name__)

# Similarity threshold: blocks above this are dedup candidates
DEDUP_SIMILARITY_THRESHOLD = 0.88
# If content overlap exceeds this ratio, auto-merge
CONTENT_OVERLAP_RATIO = 0.7
# P2: Similarity threshold that triggers LLM conflict arbitration
_CONFLICT_SIMILARITY_THRESHOLD = 0.85


class DedupDecision(Enum):
    CREATE = "create"  # No similar block found, proceed normally
    SKIP = "skip"  # Near-identical block exists, skip creation
    MERGE = "merge"  # Similar block exists, merge content
    SUPERSEDE = "supersede"  # New version supersedes old (reserved for future temporal use)


class DedupBehavior(Enum):
    ALWAYS_MERGE = "always_merge"  # Force merge even at lower similarity (e.g. attitude/opinions)
    MERGE_IF_SIMILAR = "merge_if_similar"  # Standard two-stage dedup (knowledge, general)
    APPEND_ONLY = "append_only"  # Never merge, always create new (e.g. discrete skills)
    SUPERSEDE = "supersede"  # New version replaces old (reserved, not yet active)


@dataclass
class CategoryDedupRule:
    behavior: DedupBehavior
    threshold: float  # Similarity threshold for vector pre-filter


# G8: Per-category dedup rules — maps block_type → rule
# Cannibalized from memory-lancedb-pro memory-categories.ts
CATEGORY_DEDUP_RULES: dict[str, CategoryDedupRule] = {
    "knowledge": CategoryDedupRule(
        behavior=DedupBehavior.MERGE_IF_SIMILAR,
        threshold=0.88,
    ),
    "attitude": CategoryDedupRule(
        behavior=DedupBehavior.ALWAYS_MERGE,
        threshold=0.75,  # More aggressive — opinions/preferences benefit from consolidation
    ),
    "skill": CategoryDedupRule(
        behavior=DedupBehavior.APPEND_ONLY,
        threshold=0.88,  # Threshold not used for APPEND_ONLY, kept for completeness
    ),
    "general": CategoryDedupRule(
        behavior=DedupBehavior.MERGE_IF_SIMILAR,
        threshold=0.88,
    ),
}

# Fallback rule for unknown block_types
_DEFAULT_DEDUP_RULE = CategoryDedupRule(
    behavior=DedupBehavior.MERGE_IF_SIMILAR,
    threshold=DEDUP_SIMILARITY_THRESHOLD,
)


def get_dedup_rule(block_type: str | None) -> CategoryDedupRule:
    """Look up per-category dedup rule for a given block_type.

    Falls back to MERGE_IF_SIMILAR with standard threshold for unknown types.
    """
    if block_type is None:
        return _DEFAULT_DEDUP_RULE
    return CATEGORY_DEDUP_RULES.get(block_type, _DEFAULT_DEDUP_RULE)


@dataclass
class DedupResult:
    decision: DedupDecision
    existing_block_id: str | None = None
    similarity: float = 0.0
    reason: str = ""
    block_type: str | None = field(default=None)  # block_type used for this check


async def find_similar_blocks(
    db: AsyncSession,
    space_id: str,
    embedding: list[float],
    threshold: float = DEDUP_SIMILARITY_THRESHOLD,
    limit: int = 3,
    content: str | None = None,
) -> list[tuple[str, str, float]]:
    """Find existing blocks with similar embeddings.

    Returns list of (block_id, content, similarity) tuples.

    Primary path: Qdrant hybrid search (dense + BM25 fusion) when available.
    Fallback: pgvector cosine_distance query (always kept for reliability).
    """
    # --- Qdrant path (primary) ---
    if content and await qdrant_available():
        try:
            config = SearchConfig(
                top_k=limit,
                score_threshold=threshold,
                service_ids=["memvault"],
                use_sparse=True,
                use_dense=True,
            )
            results, _meta = await hybrid_search(content, space_id, config)
            if results:
                # Qdrant returns entity_id (= block_id) + content_preview.
                # We need full content for Stage 2 comparisons — fetch from DB.
                block_ids = [r.entity_id for r in results]
                q_content = select(MemoryBlock.id, MemoryBlock.content).where(
                    MemoryBlock.id.in_(block_ids),
                    MemoryBlock.deleted_at == None,  # noqa: E711
                )
                rows_map = {str(row[0]): str(row[1]) for row in (await db.execute(q_content)).all()}
                tuples = []
                for r in results:
                    block_content = rows_map.get(r.entity_id)
                    if block_content is not None:
                        tuples.append((r.entity_id, block_content, float(r.score)))
                if tuples:
                    return tuples
                # Fall through if DB lookup returned nothing (stale index)
        except Exception:
            logger.warning("Qdrant dedup search failed, falling back to pgvector", exc_info=True)

    # --- pgvector fallback (legacy) ---
    if len(embedding) != EMBEDDING_DIM:
        return []

    distance = BlockEmbedding.embedding.cosine_distance(embedding)
    similarity = (1 - distance).label("similarity")

    q = (
        select(MemoryBlock.id, MemoryBlock.content, similarity)
        .join(BlockEmbedding, BlockEmbedding.block_id == MemoryBlock.id)
        .where(
            MemoryBlock.space_id == space_id,
            MemoryBlock.deleted_at == None,  # noqa: E711
            distance < (1 - threshold),
        )
        .order_by(distance)
        .limit(limit)
    )

    rows = (await db.execute(q)).all()
    return [(str(row[0]), str(row[1]), float(row[2])) for row in rows]


def _content_overlap(a: str, b: str) -> float:
    """Compute Jaccard similarity of word sets."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


async def check_duplicate(
    db: AsyncSession,
    space_id: str,
    content: str,
    embedding: list[float],
    threshold: float = DEDUP_SIMILARITY_THRESHOLD,
    block_type: str | None = None,
) -> DedupResult:
    """Two-stage, category-aware dedup check before block creation.

    G8: Looks up per-category rule (DedupBehavior) for block_type, then applies
    behavior-specific thresholds and decisions.

    Stage 1: Vector similarity search for candidates (threshold from category rule)
    Stage 2: Content comparison to decide action (logic from category rule)

    Backward-compatible: block_type=None falls back to MERGE_IF_SIMILAR with
    the default threshold, identical to the original behavior.
    """
    # G8: Resolve category-specific rule
    rule = get_dedup_rule(block_type)
    effective_threshold = threshold if threshold != DEDUP_SIMILARITY_THRESHOLD else rule.threshold

    # APPEND_ONLY: skip all similarity checks, always create
    if rule.behavior == DedupBehavior.APPEND_ONLY:
        return DedupResult(
            decision=DedupDecision.CREATE,
            reason=f"append_only ({block_type})",
            block_type=block_type,
        )

    # Stage 1: Find similar blocks using category threshold.
    # Pass content so Qdrant path can use hybrid search; pgvector path uses embedding.
    similar = await find_similar_blocks(
        db, space_id, embedding, effective_threshold, content=content
    )

    if not similar:
        return DedupResult(
            decision=DedupDecision.CREATE,
            reason="no_similar_found",
            block_type=block_type,
        )

    # Stage 2: Content comparison — behavior-specific logic
    best_id, best_content, best_sim = similar[0]

    # ALWAYS_MERGE: any candidate above threshold → merge immediately (no content check)
    if rule.behavior == DedupBehavior.ALWAYS_MERGE:
        return DedupResult(
            decision=DedupDecision.MERGE,
            existing_block_id=best_id,
            similarity=best_sim,
            reason=f"always_merge ({block_type}, sim={best_sim:.3f})",
            block_type=block_type,
        )

    # MERGE_IF_SIMILAR (default): original two-stage content comparison
    # Very high similarity (>0.95) = almost certainly duplicate
    if best_sim > 0.95:
        overlap = _content_overlap(content, best_content)
        if overlap > CONTENT_OVERLAP_RATIO:
            return DedupResult(
                decision=DedupDecision.SKIP,
                existing_block_id=best_id,
                similarity=best_sim,
                reason=f"near_identical (sim={best_sim:.3f}, overlap={overlap:.2f})",
                block_type=block_type,
            )

    # P2: LLM conflict arbitration for uncertain zone (0.85-0.95 similarity)
    # Instead of simple content overlap, use LLM to determine MERGE / SUPERSEDE / COEXIST
    if best_sim >= _CONFLICT_SIMILARITY_THRESHOLD:
        try:
            from .conflict_resolver import ConflictDecision, resolve_conflict

            cr = await resolve_conflict(
                new_content=content,
                existing_content=best_content,
                existing_block_id=best_id,
                block_type=block_type or "general",
                similarity=best_sim,
            )
            decision_map = {
                ConflictDecision.MERGE: DedupDecision.MERGE,
                ConflictDecision.SUPERSEDE: DedupDecision.SUPERSEDE,
                ConflictDecision.COEXIST: DedupDecision.CREATE,
            }
            return DedupResult(
                decision=decision_map.get(cr.decision, DedupDecision.CREATE),
                existing_block_id=best_id,
                similarity=best_sim,
                reason=f"conflict_resolver:{cr.decision.value} ({cr.reason})",
                block_type=block_type,
            )
        except Exception:
            logger.warning("conflict_resolver failed, falling back to heuristic", exc_info=True)

    # Fallback: High similarity (threshold~0.95) — check content overlap
    overlap = _content_overlap(content, best_content)
    if overlap > CONTENT_OVERLAP_RATIO:
        return DedupResult(
            decision=DedupDecision.MERGE,
            existing_block_id=best_id,
            similarity=best_sim,
            reason=f"high_overlap (sim={best_sim:.3f}, overlap={overlap:.2f})",
            block_type=block_type,
        )

    # Similar embedding but different content — new perspective on same topic
    return DedupResult(
        decision=DedupDecision.CREATE,
        reason=f"different_content (sim={best_sim:.3f}, overlap={overlap:.2f})",
        block_type=block_type,
    )


def merge_content(existing: str, new: str) -> str:
    """Merge new content into existing, preserving both perspectives.

    Simple strategy: append new info that isn't already in existing.
    """
    existing_words = set(existing.lower().split())
    new_sentences = [s.strip() for s in new.split(".") if s.strip()]

    additions = []
    for sentence in new_sentences:
        sentence_words = set(sentence.lower().split())
        # If less than 50% of sentence words are in existing, it's new info
        if sentence_words and len(sentence_words & existing_words) / len(sentence_words) < 0.5:
            additions.append(sentence)

    if not additions:
        return existing  # Nothing new to add

    return existing.rstrip() + "\n" + ". ".join(additions) + "."
