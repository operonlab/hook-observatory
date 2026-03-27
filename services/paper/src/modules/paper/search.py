"""Paper semantic search engine — Qdrant hybrid search with ILIKE text fallback + reranking.

Graceful degradation:
1. Qdrant hybrid (dense + sparse) -> primary
2. ILIKE text search -> if Qdrant unavailable or returns empty
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.fallback_search import build_ilike_conditions, score_text_match
from src.shared.qdrant_client import is_available as qdrant_available
from src.shared.qdrant_search import hybrid_search as qdrant_hybrid_search
from src.shared.rerank_utils import rerank_generic
from src.shared.search_types import SearchConfig as QdrantSearchConfig

from .models import Article
from .schemas import ArticleBrief, PaperSearchResult, SearchRequest

logger = logging.getLogger(__name__)


async def search_articles(
    db: AsyncSession,
    space_id: str,
    request: SearchRequest,
) -> list[PaperSearchResult]:
    """Search articles using Qdrant hybrid -> ILIKE text fallback.

    Applies optional filters: categories, tags, year range.
    Results are reranked using cross-encoder for precision.
    """
    if await qdrant_available():
        results = await _qdrant_search(db, space_id, request)
        if results:
            return results
        # Qdrant returned nothing — fall back to ILIKE text search
        logger.debug(
            "Qdrant returned 0 results for space=%s query=%r — falling back to ILIKE",
            space_id,
            request.query,
        )

    return await _ilike_fallback(db, space_id, request)


async def _qdrant_search(
    db: AsyncSession,
    space_id: str,
    request: SearchRequest,
) -> list[PaperSearchResult]:
    """Search via Qdrant hybrid search."""
    config = QdrantSearchConfig(
        top_k=request.limit,
        score_threshold=request.threshold,
        service_ids=["paper"],
    )
    results, _meta = await qdrant_hybrid_search(request.query, space_id, config)

    if not results:
        return []

    # Fetch full Article rows to apply filters and enrich with digest data
    article_ids = [r.entity_id for r in results]
    score_map = {r.entity_id: r.score for r in results}

    q = select(Article).where(
        Article.id.in_(article_ids),
        Article.deleted_at == None,  # noqa: E711
    )
    q = _apply_filters(q, request)
    rows = (await db.execute(q)).scalars().all()

    search_results = [
        PaperSearchResult(
            article=_to_brief(a),
            score=round(score_map.get(a.id, 0.0), 4),
            digest_one_liner=a.digest.one_liner if a.digest else None,
            workshop_relevance=a.digest.workshop_relevance if a.digest else None,
        )
        for a in rows
    ]

    return await _rerank(request.query, search_results)


async def _ilike_fallback(
    db: AsyncSession,
    space_id: str,
    request: SearchRequest,
) -> list[PaperSearchResult]:
    """ILIKE text search fallback when embedding is unavailable."""
    conditions = build_ilike_conditions(request.query, Article.title, Article.abstract)

    q = (
        select(Article)
        .where(
            Article.space_id == space_id,
            Article.deleted_at == None,  # noqa: E711
            *conditions,
        )
        .order_by(Article.created_at.desc())
        .limit(request.limit)
    )
    q = _apply_filters(q, request)
    rows = (await db.execute(q)).scalars().all()

    return [
        PaperSearchResult(
            article=_to_brief(a),
            score=round(
                score_text_match(request.query, (a.abstract or "") + " " + a.title, tier="hot"),
                4,
            ),
            digest_one_liner=a.digest.one_liner if a.digest else None,
            workshop_relevance=a.digest.workshop_relevance if a.digest else None,
        )
        for a in rows
    ]


def _apply_filters(q, request: SearchRequest):
    """Apply optional metadata filters to a query."""
    if request.categories:
        q = q.where(Article.categories.contains(request.categories))
    if request.tags:
        q = q.where(Article.tags.contains(request.tags))
    if request.year_from is not None:
        q = q.where(Article.year >= request.year_from)
    if request.year_to is not None:
        q = q.where(Article.year <= request.year_to)
    return q


async def _rerank(query: str, results: list[PaperSearchResult]) -> list[PaperSearchResult]:
    """Cross-encoder reranking."""
    return await rerank_generic(
        query=query,
        results=results,
        content_fn=lambda r: f"{r.article.title} {' '.join(r.article.categories)}",
        score_fn=lambda r: r.score,
        set_score_fn=lambda r, s: setattr(r, "score", s),
    )


def _to_brief(article: Article) -> ArticleBrief:
    """Convert ORM Article to lightweight ArticleBrief."""
    return ArticleBrief(
        id=article.id,
        title=article.title,
        arxiv_id=article.arxiv_id,
        doi=article.doi,
        year=article.year,
        authors=article.authors or [],
        journal=article.journal,
        categories=article.categories or [],
        tags=article.tags or [],
        created_at=article.created_at,
    )
