"""Intelflow semantic search engine — pgvector cosine similarity.

Graceful degradation: falls back to ILIKE text search when Ollama is unavailable.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.embedding import get_embedding
from src.shared.tier_config import get_threshold

from .models import Report, ReportArchive, ReportEmbedding
from .schemas import (
    ReportBrief,
    SearchCheckResponse,
    SearchMatchResult,
    SemanticSearchResult,
)

logger = logging.getLogger(__name__)


async def semantic_search(
    db: AsyncSession,
    space_id: str,
    query: str,
    limit: int = 10,
    threshold: float = 0.5,
    include_archived: bool = False,
    include_warm: bool = True,
) -> list[SemanticSearchResult]:
    """Search reports by semantic similarity. Falls back to text.

    Tries report_embeddings sub-table first (Phase 2);
    falls back to inline reports.embedding.

    When include_warm=True (default), augments with warm-tier
    text search (score x 0.7) for reports between hot_days and
    warm_days age that no longer have HNSW indexes.
    """
    query_embedding = await get_embedding(query)
    if query_embedding is None:
        return await _text_search_fallback(
            db, space_id, query, limit,
            include_archived, include_warm,
        )

    # Phase 2 path: sub-table
    results = await _search_via_subtable(
        db, space_id, query_embedding, limit, threshold,
    )

    if not results:
        # Fallback: inline embedding
        distance = Report.embedding.cosine_distance(
            query_embedding,
        )
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
        results = [
            SemanticSearchResult(
                report=_to_brief(row.Report),
                score=round(float(row.similarity), 4),
            )
            for row in rows
        ]

    # Warm tier: text-based augmentation for older reports
    if include_warm and len(results) < limit:
        warm_results = await _warm_tier_search(
            db, space_id, query,
            limit - len(results),
        )
        results.extend(warm_results)

    return results


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


async def _warm_tier_search(
    db: AsyncSession,
    space_id: str,
    query: str,
    remaining: int,
) -> list[SemanticSearchResult]:
    """Search warm-tier reports (no HNSW, still in main table).

    Warm tier: hot_days < age <= warm_days.
    Uses ILIKE on title + content; score = 0.5 * 0.7 = 0.35.
    """
    tier = get_threshold("intelflow")
    now = datetime.now(UTC)
    hot_cutoff = now - timedelta(days=tier.hot_days)
    warm_cutoff = now - timedelta(days=tier.warm_days)
    pattern = f"%{query}%"

    q = (
        select(Report)
        .where(
            Report.space_id == space_id,
            (
                Report.title.ilike(pattern)
                | Report.content.ilike(pattern)
            ),
            Report.created_at < hot_cutoff,
            Report.created_at >= warm_cutoff,
        )
        .order_by(Report.updated_at.desc())
        .limit(remaining)
    )

    rows = (await db.execute(q)).scalars().all()
    return [
        SemanticSearchResult(
            report=_to_brief(r),
            score=0.35,  # warm tier: 0.5 * 0.7
        )
        for r in rows
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
    include_warm: bool = True,
) -> list[SemanticSearchResult]:
    """Fallback text search using ILIKE when Ollama unavailable.

    Tier-aware search:
      Hot  (age <= hot_days): score 0.5
      Warm (hot_days < age <= warm_days): score 0.35
      Cold (archive table, include_archived): score 0.3
    """
    pattern = f"%{query}%"
    tier = get_threshold("intelflow")
    now = datetime.now(UTC)
    hot_cutoff = now - timedelta(days=tier.hot_days)
    warm_cutoff = now - timedelta(days=tier.warm_days)
    ilike_cond = (
        Report.title.ilike(pattern)
        | Report.content.ilike(pattern)
    )

    # --- Hot tier ---
    hot_q = (
        select(Report)
        .where(
            Report.space_id == space_id,
            ilike_cond,
            Report.created_at >= hot_cutoff,
        )
        .order_by(Report.updated_at.desc())
        .limit(limit)
    )
    hot_rows = (await db.execute(hot_q)).scalars().all()
    results: list[SemanticSearchResult] = [
        SemanticSearchResult(
            report=_to_brief(r), score=0.5,
        )
        for r in hot_rows
    ]

    # --- Warm tier ---
    if include_warm and len(results) < limit:
        remaining = limit - len(results)
        warm_q = (
            select(Report)
            .where(
                Report.space_id == space_id,
                ilike_cond,
                Report.created_at < hot_cutoff,
                Report.created_at >= warm_cutoff,
            )
            .order_by(Report.updated_at.desc())
            .limit(remaining)
        )
        warm_rows = (
            await db.execute(warm_q)
        ).scalars().all()
        results.extend([
            SemanticSearchResult(
                report=_to_brief(r),
                score=0.35,  # warm: 0.5 * 0.7
            )
            for r in warm_rows
        ])

    # --- Cold tier: archive table ---
    if include_archived and len(results) < limit:
        remaining = limit - len(results)
        archive_ilike = (
            ReportArchive.title.ilike(pattern)
            | ReportArchive.content.ilike(pattern)
        )
        archive_q = (
            select(ReportArchive)
            .where(
                ReportArchive.space_id == space_id,
                archive_ilike,
                ~ReportArchive.content.like("s3://%"),
            )
            .order_by(ReportArchive.created_at.desc())
            .limit(remaining)
        )
        archive_rows = (
            await db.execute(archive_q)
        ).scalars().all()
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
                score=0.3,  # cold: archived result
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
