"""Intelflow semantic search engine — pgvector cosine similarity.

Graceful degradation: falls back to ILIKE text search when Ollama is unavailable.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.embedding import get_embedding

from .models import Report, ReportArchive, ReportEmbedding
from .schemas import ReportBrief, SearchCheckResponse, SearchMatchResult, SemanticSearchResult

logger = logging.getLogger(__name__)


async def semantic_search(
    db: AsyncSession,
    space_id: str,
    query: str,
    limit: int = 10,
    threshold: float = 0.5,
    include_archived: bool = False,
) -> list[SemanticSearchResult]:
    """Search reports by semantic similarity. Falls back to text search.

    Tries report_embeddings sub-table first (Phase 2);
    falls back to inline reports.embedding.
    """
    query_embedding = await get_embedding(query)
    if query_embedding is None:
        return await _text_search_fallback(db, space_id, query, limit, include_archived)

    # Phase 2 path: sub-table
    results = await _search_via_subtable(db, space_id, query_embedding, limit, threshold)
    if results:
        return results

    # Fallback: inline embedding
    distance = Report.embedding.cosine_distance(query_embedding)
    similarity = (1 - distance).label("similarity")

    q = (
        select(Report, similarity)
        .where(
            Report.space_id == space_id,
            Report.embedding.isnot(None),
            distance < (1 - threshold),
        )
        .order_by(distance)
        .limit(limit)
    )

    rows = (await db.execute(q)).all()
    return [
        SemanticSearchResult(
            report=_to_brief(row.Report),
            score=round(float(row.similarity), 4),
        )
        for row in rows
    ]


async def _search_via_subtable(
    db: AsyncSession,
    space_id: str,
    query_embedding: list[float],
    limit: int,
    threshold: float,
) -> list[SemanticSearchResult]:
    """Search using the report_embeddings sub-table (Phase 2)."""
    distance = ReportEmbedding.embedding.cosine_distance(query_embedding)
    similarity = (1 - distance).label("similarity")

    q = (
        select(Report, similarity)
        .join(ReportEmbedding, ReportEmbedding.report_id == Report.id)
        .where(
            Report.space_id == space_id,
            distance < (1 - threshold),
        )
        .order_by(distance)
        .limit(limit)
    )

    rows = (await db.execute(q)).all()
    return [
        SemanticSearchResult(
            report=_to_brief(row.Report),
            score=round(float(row.similarity), 4),
        )
        for row in rows
    ]


async def check_duplicate(
    db: AsyncSession,
    space_id: str,
    query: str,
    threshold: float = 0.85,
) -> SearchCheckResponse:
    """Check if a similar report already exists (deduplication)."""
    query_embedding = await get_embedding(query)
    if query_embedding is None:
        # Cannot check without embeddings — assume no match
        return SearchCheckResponse(exists=False, matches=[])

    distance = Report.embedding.cosine_distance(query_embedding)
    similarity = (1 - distance).label("similarity")

    q = (
        select(Report, similarity)
        .where(
            Report.space_id == space_id,
            Report.embedding.isnot(None),
            distance < (1 - threshold),
        )
        .order_by(distance)
        .limit(5)
    )

    rows = (await db.execute(q)).all()
    matches = [
        SearchMatchResult(
            report=_to_brief(row.Report),
            score=round(float(row.similarity), 4),
        )
        for row in rows
    ]
    return SearchCheckResponse(exists=len(matches) > 0, matches=matches)


async def _text_search_fallback(
    db: AsyncSession,
    space_id: str,
    query: str,
    limit: int = 10,
    include_archived: bool = False,
) -> list[SemanticSearchResult]:
    """Fallback text search using ILIKE when Ollama is unavailable."""
    pattern = f"%{query}%"
    q = (
        select(Report)
        .where(
            Report.space_id == space_id,
            (Report.title.ilike(pattern) | Report.content.ilike(pattern)),
        )
        .order_by(Report.updated_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(q)).scalars().all()
    results = [
        SemanticSearchResult(report=_to_brief(r), score=0.5)
        for r in rows
    ]

    # Phase 3: search archived reports if requested and under limit
    if include_archived and len(results) < limit:
        remaining = limit - len(results)
        archive_q = (
            select(ReportArchive)
            .where(
                ReportArchive.space_id == space_id,
                (ReportArchive.title.ilike(pattern) | ReportArchive.content.ilike(pattern)),
            )
            .order_by(ReportArchive.created_at.desc())
            .limit(remaining)
        )
        archive_rows = (await db.execute(archive_q)).scalars().all()
        results.extend([
            SemanticSearchResult(
                report=ReportBrief(
                    id=r.id,
                    title=r.title,
                    query=r.query,
                    tags=r.tags or [],
                    skill_name=r.skill_name,
                    created_at=r.created_at,
                ),
                score=0.3,  # lower score indicates archived result
            )
            for r in archive_rows
        ])

    return results


def _to_brief(report: Report) -> ReportBrief:
    """Convert ORM Report to lightweight ReportBrief."""
    return ReportBrief(
        id=report.id,
        title=report.title,
        query=report.query,
        tags=report.tags or [],
        skill_name=report.skill_name,
        created_at=report.created_at,
    )
