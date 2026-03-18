"""Intelflow semantic search engine — Qdrant hybrid search (primary) with ILIKE text fallback.

Graceful degradation: Qdrant -> ILIKE text search (when Qdrant unavailable).
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.fallback_search import (
    SERVICE_AVGDL,
    build_ilike_conditions,
    score_text_match,
)
from src.shared.qdrant_client import is_available as qdrant_available
from src.shared.qdrant_search import hybrid_search as qdrant_hybrid_search
from src.shared.rerank_utils import rerank_generic
from src.shared.search_types import SearchConfig as QdrantSearchConfig
from src.shared.tier_config import get_threshold

from .models import Report, ReportArchive
from .schemas import (
    ReportBrief,
    SearchCheckResponse,
    SearchMatchResult,
    SemanticSearchResult,
)

logger = logging.getLogger(__name__)


async def qdrant_search(
    db: AsyncSession,
    space_id: str,
    query: str,
    limit: int = 10,
    threshold: float = 0.3,
    include_archived: bool = False,
    include_warm: bool = True,
) -> list[SemanticSearchResult]:
    """Search using Qdrant hybrid (dense + sparse).

    Falls back to ILIKE text search when Qdrant is unavailable.
    Empty results from Qdrant are returned as-is (not forwarded to fallback).
    """
    if not await qdrant_available():
        logger.warning("Qdrant unavailable — using ILIKE text search fallback for intelflow")
        return await _text_search_fallback(
            db,
            space_id,
            query,
            limit,
            include_archived,
            include_warm,
        )

    config = QdrantSearchConfig(
        top_k=limit,
        score_threshold=threshold,
        service_ids=["intelflow"],
    )
    results, _meta = await qdrant_hybrid_search(query, space_id, config)

    if not results:
        # Qdrant available but found no matches — return empty (no further fallback)
        logger.debug("Qdrant returned 0 results for space=%s query=%r", space_id, query)
        return []

    # Convert Qdrant SearchResult → intelflow SemanticSearchResult
    # Qdrant payload has created_at but may lack title/query — hydrate from DB
    entity_ids = [r.entity_id for r in results]
    score_map = {r.entity_id: r.score for r in results}

    stmt = select(Report).where(Report.id.in_(entity_ids))
    rows = (await db.execute(stmt)).scalars().all()
    report_map = {str(r.id): r for r in rows}

    hydrated = []
    for eid in entity_ids:
        report = report_map.get(eid)
        if not report:
            continue
        hydrated.append(
            SemanticSearchResult(
                report=_to_brief(report),
                score=score_map[eid],
            )
        )
    return hydrated


async def semantic_search(
    db: AsyncSession,
    space_id: str,
    query: str,
    limit: int = 10,
    threshold: float = 0.5,
    include_archived: bool = False,
    include_warm: bool = True,
) -> list[SemanticSearchResult]:
    """Text search with warm-tier augmentation and cross-encoder reranking.

    Delegates to ILIKE text search, augments with warm tier,
    then reranks via cross-encoder. pgvector path removed (Qdrant migration).
    """
    results = await _text_search_fallback(
        db,
        space_id,
        query,
        limit,
        include_archived,
        include_warm,
    )

    # Warm tier: text-based augmentation for older reports
    if include_warm and len(results) < limit:
        warm_results = await _warm_tier_search(
            db,
            space_id,
            query,
            limit - len(results),
        )
        results.extend(warm_results)

    # Cross-encoder reranking
    results = await rerank_generic(
        query=query,
        results=results,
        content_fn=lambda r: f"{r.report.title} {r.report.query}",
        score_fn=lambda r: r.score,
        set_score_fn=lambda r, s: setattr(r, "score", s),
    )

    return results


async def _warm_tier_search(
    db: AsyncSession,
    space_id: str,
    query: str,
    remaining: int,
) -> list[SemanticSearchResult]:
    """Search warm-tier reports (no HNSW, still in main table).

    Warm tier: hot_days < age <= warm_days.
    Uses CJK-aware jieba multi-term ILIKE + BM25-lite scoring.
    """
    tier = get_threshold("intelflow")
    now = datetime.now(UTC)
    hot_cutoff = now - timedelta(days=tier.hot_days)
    warm_cutoff = now - timedelta(days=tier.warm_days)
    avgdl = SERVICE_AVGDL.get("intelflow", SERVICE_AVGDL["default"])

    conditions = build_ilike_conditions(query, Report.title, Report.content)

    q = (
        select(Report)
        .where(
            Report.space_id == space_id,
            *conditions,
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
            score=round(score_text_match(query, r.content or r.title, tier="warm", avgdl=avgdl), 4),
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
    results = await qdrant_search(db, space_id, query, limit=5, threshold=threshold)
    matches = [SearchMatchResult(report=r.report, score=r.score) for r in results]
    return SearchCheckResponse(exists=len(matches) > 0, matches=matches)


async def _text_search_fallback(
    db: AsyncSession,
    space_id: str,
    query: str,
    limit: int = 10,
    include_archived: bool = False,
    include_warm: bool = True,
) -> list[SemanticSearchResult]:
    """Fallback text search using CJK-aware ILIKE + BM25-lite when oMLX unavailable.

    Tier-aware search with per-token matching and BM25-lite scoring:
      Hot  (age <= hot_days): BM25-lite * hot_base
      Warm (hot_days < age <= warm_days): BM25-lite * warm_decay
      Cold (archive table, include_archived): BM25-lite * cold_decay
    """
    tier = get_threshold("intelflow")
    now = datetime.now(UTC)
    hot_cutoff = now - timedelta(days=tier.hot_days)
    warm_cutoff = now - timedelta(days=tier.warm_days)
    avgdl = SERVICE_AVGDL.get("intelflow", SERVICE_AVGDL["default"])

    conditions = build_ilike_conditions(query, Report.title, Report.content)

    # --- Hot tier ---
    hot_q = (
        select(Report)
        .where(
            Report.space_id == space_id,
            *conditions,
            Report.created_at >= hot_cutoff,
        )
        .order_by(Report.updated_at.desc())
        .limit(limit)
    )
    hot_rows = (await db.execute(hot_q)).scalars().all()
    results: list[SemanticSearchResult] = [
        SemanticSearchResult(
            report=_to_brief(r),
            score=round(score_text_match(query, r.content or r.title, tier="hot", avgdl=avgdl), 4),
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
                *conditions,
                Report.created_at < hot_cutoff,
                Report.created_at >= warm_cutoff,
            )
            .order_by(Report.updated_at.desc())
            .limit(remaining)
        )
        warm_rows = (await db.execute(warm_q)).scalars().all()
        results.extend(
            [
                SemanticSearchResult(
                    report=_to_brief(r),
                    score=round(
                        score_text_match(query, r.content or r.title, tier="warm", avgdl=avgdl),
                        4,
                    ),
                )
                for r in warm_rows
            ]
        )

    # --- Cold tier: archive table ---
    if include_archived and len(results) < limit:
        remaining = limit - len(results)
        archive_conditions = build_ilike_conditions(
            query,
            ReportArchive.title,
            ReportArchive.content,
        )
        archive_q = (
            select(ReportArchive)
            .where(
                ReportArchive.space_id == space_id,
                *archive_conditions,
                ~ReportArchive.content.like("s3://%"),
            )
            .order_by(ReportArchive.created_at.desc())
            .limit(remaining)
        )
        archive_rows = (await db.execute(archive_q)).scalars().all()
        results.extend(
            [
                SemanticSearchResult(
                    report=ReportBrief(
                        id=r.id,
                        title=r.title,
                        query=r.query,
                        tags=r.tags or [],
                        skill_name=r.skill_name,
                        created_at=r.created_at,
                    ),
                    score=round(
                        score_text_match(query, r.content or r.title, tier="cold", avgdl=avgdl),
                        4,
                    ),
                )
                for r in archive_rows
            ]
        )

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
