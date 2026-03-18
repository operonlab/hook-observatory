"""Generic cross-encoder reranking utility for any module.

Wraps rerank_bridge to provide a simple interface for reranking
arbitrary result lists with a content extraction function.
"""

import logging
from collections.abc import Callable

from . import rerank_bridge

logger = logging.getLogger(__name__)


async def rerank_generic[T](
    query: str,
    results: list[T],
    content_fn: Callable[[T], str],
    score_fn: Callable[[T], float],
    set_score_fn: Callable[[T, float], None],
    *,
    max_candidates: int = 20,
    snippet_length: int = 500,
    weight_original: float = 0.3,
    weight_rerank: float = 0.7,
) -> list[T]:
    """Rerank any result list using cross-encoder.

    Args:
        query: Search query
        results: List of result objects (any type)
        content_fn: Extract text content from a result
        score_fn: Extract current score from a result
        set_score_fn: Set blended score on a result
        max_candidates: Max items to rerank
        snippet_length: Truncate content to this length
        weight_original: Blend weight for original score
        weight_rerank: Blend weight for cross-encoder score

    Returns:
        Re-sorted results list. Falls back to original order if reranker unavailable.
    """
    if len(results) <= 1:
        return results

    candidates = results[:max_candidates]
    remainder = results[max_candidates:]

    snippets = [content_fn(r)[:snippet_length] for r in candidates]

    scores = await rerank_bridge.rerank(query, snippets)
    if scores is None:
        return results

    score_map = {s["index"]: s["score"] for s in scores}

    if len(scores) != len(candidates):
        logger.warning(
            "Rerank score count mismatch: sent %d, got %d",
            len(candidates),
            len(scores),
        )

    for i, r in enumerate(candidates):
        ce_score = score_map.get(i)
        if ce_score is not None:
            ce_normalized = (ce_score + 1) / 2
            blended = weight_original * score_fn(r) + weight_rerank * ce_normalized
            set_score_fn(r, blended)

    candidates.sort(key=score_fn, reverse=True)
    return candidates + remainder
