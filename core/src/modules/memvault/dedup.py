"""G1: Block-level deduplication — prevent memory bloat from duplicate content.

Adapted from memory-lancedb-pro's two-stage dedup:
Stage 1: Vector similarity pre-filter (fast, DB-level)
Stage 2: Content comparison decision (merge/skip/create)
"""

import logging
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import EMBEDDING_DIM, BlockEmbedding, MemoryBlock

logger = logging.getLogger(__name__)

# Similarity threshold: blocks above this are dedup candidates
DEDUP_SIMILARITY_THRESHOLD = 0.88
# If content overlap exceeds this ratio, auto-merge
CONTENT_OVERLAP_RATIO = 0.7


class DedupDecision(Enum):
    CREATE = "create"  # No similar block found, proceed normally
    SKIP = "skip"  # Near-identical block exists, skip creation
    MERGE = "merge"  # Similar block exists, merge content


@dataclass
class DedupResult:
    decision: DedupDecision
    existing_block_id: str | None = None
    similarity: float = 0.0
    reason: str = ""


async def find_similar_blocks(
    db: AsyncSession,
    space_id: str,
    embedding: list[float],
    threshold: float = DEDUP_SIMILARITY_THRESHOLD,
    limit: int = 3,
) -> list[tuple[str, str, float]]:
    """Find existing blocks with similar embeddings.

    Returns list of (block_id, content, similarity) tuples.
    """
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
) -> DedupResult:
    """Two-stage dedup check before block creation.

    Stage 1: Vector similarity search for candidates
    Stage 2: Content comparison to decide action
    """
    # Stage 1: Find similar blocks by embedding
    similar = await find_similar_blocks(db, space_id, embedding, threshold)

    if not similar:
        return DedupResult(decision=DedupDecision.CREATE, reason="no_similar_found")

    # Stage 2: Content comparison
    best_id, best_content, best_sim = similar[0]

    # Very high similarity (>0.95) = almost certainly duplicate
    if best_sim > 0.95:
        overlap = _content_overlap(content, best_content)
        if overlap > CONTENT_OVERLAP_RATIO:
            return DedupResult(
                decision=DedupDecision.SKIP,
                existing_block_id=best_id,
                similarity=best_sim,
                reason=f"near_identical (sim={best_sim:.3f}, overlap={overlap:.2f})",
            )

    # High similarity (threshold~0.95) — check content overlap
    overlap = _content_overlap(content, best_content)
    if overlap > CONTENT_OVERLAP_RATIO:
        return DedupResult(
            decision=DedupDecision.MERGE,
            existing_block_id=best_id,
            similarity=best_sim,
            reason=f"high_overlap (sim={best_sim:.3f}, overlap={overlap:.2f})",
        )

    # Similar embedding but different content — new perspective on same topic
    return DedupResult(
        decision=DedupDecision.CREATE,
        reason=f"different_content (sim={best_sim:.3f}, overlap={overlap:.2f})",
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
