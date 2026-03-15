"""Intelflow routes — REST API endpoints.

Prefix: /api/intelflow (mounted in main.py)
"""

import json
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.embedding import get_embedding
from src.shared.errors import BadRequestError, NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams
from src.shared.storage import (
    compute_content_hash,
    download_and_decompress,
)

from . import search as search_engine
from .schemas import (
    DashboardResponse,
    ReportCreate,
    ReportResponse,
    ReportUpdate,
    SearchCheckRequest,
    SearchCheckResponse,
    SearchRequest,
    SemanticSearchResult,
    TimelineResponse,
    TopicCreate,
    TopicGraphResponse,
    TopicResponse,
)
from .services import (
    dashboard_service,
    report_service,
    search_session_service,
    topic_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["intelflow"])


# ======================== Reports ========================


@router.get("/reports", response_model=PaginatedResponse[ReportResponse])
async def list_reports(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tag: str | None = Query(None),
    tags: str | None = Query(None, description="Comma-separated tags"),
    topic_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.read"),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    tag_list = None
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    elif tag:
        tag_list = [tag]

    if tag_list:
        return await report_service.list_by_tags(db, space_id, tag_list, pagination)
    if topic_id:
        return await report_service.list_by_topic(db, space_id, topic_id, pagination)
    return await report_service.list(db, space_id, pagination)


@router.get("/reports/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.read"),
):
    instance = await report_service.get_with_content_resolve(db, report_id)
    if not instance:
        raise NotFoundError("Report not found", code="intelflow.report_not_found")
    # Resolve S3 content references for archived reports
    from src.shared.storage import is_s3_ref, resolve_content

    content = instance.content
    if is_s3_ref(content):
        resolved = await resolve_content(content)
        if resolved:
            content = resolved
    return ReportResponse(
        id=instance.id,
        space_id=instance.space_id,
        created_by=instance.created_by,
        created_at=instance.created_at,
        updated_at=instance.updated_at,
        title=instance.title,
        query=getattr(instance, "query", ""),
        content=content,
        sources=getattr(instance, "sources", None) or [],
        tags=getattr(instance, "tags", None) or [],
        skill_name=getattr(instance, "skill_name", None),
        topics=[],
    )


@router.post("/reports", response_model=ReportResponse, status_code=201)
async def create_report(
    body: ReportCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.write"),
):
    # Strip skill_name from tags to avoid pollution
    if body.skill_name and body.tags:
        skip_tag = body.skill_name.strip().lower()
        body.tags = [t for t in body.tags if t.strip().lower() != skip_tag]
    instance = await report_service.create(db, space_id, body)
    # Override created_at if provided (for migration)
    if body.created_at:
        instance.created_at = body.created_at
    # Generate embedding (best-effort) — never block report creation
    try:
        embedding = await get_embedding(f"{instance.title} {instance.query}")
        if embedding:
            instance.embedding = embedding
            from .models import ReportEmbedding

            db.add(ReportEmbedding(report_id=instance.id, embedding=embedding))
    except Exception:
        logger.warning("Failed to generate embedding for report %s", instance.id, exc_info=True)
    await db.commit()
    await db.refresh(instance)
    # Extract topics from tags (best-effort)
    try:
        if instance.tags:
            await topic_service.extract_from_report(db, instance)
    except Exception:
        logger.warning("Failed to extract topics for report %s", instance.id, exc_info=True)
    # Record search session (best-effort)
    try:
        await search_session_service.record(
            db,
            space_id,
            body.query,
            source=body.skill_name,
            result_type="new_report",
            report_id=instance.id,
        )
    except Exception:
        logger.warning("Failed to record search session for report %s", instance.id, exc_info=True)
    await db.commit()
    await db.refresh(instance)
    return report_service.to_response(instance)


@router.put("/reports/{report_id}", response_model=ReportResponse)
async def update_report(
    report_id: str,
    body: ReportUpdate,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.write"),
):
    instance = await report_service.update(db, report_id, body)
    if not instance:
        raise NotFoundError("Report not found", code="intelflow.report_not_found")
    await db.commit()
    await db.refresh(instance)
    return report_service.to_response(instance)


@router.delete("/reports/{report_id}", status_code=204)
async def delete_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.write"),
):
    deleted = await report_service.delete(db, report_id)
    if not deleted:
        raise NotFoundError("Report not found", code="intelflow.report_not_found")
    await db.commit()


# ======================== Search ========================


@router.post("/search", response_model=list[SemanticSearchResult])
async def search_reports(
    body: SearchRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.read"),
):
    results = await search_engine.semantic_search(
        db, space_id, body.query, limit=body.limit, threshold=body.threshold
    )
    # Record search session (non-critical — degrade gracefully on failure)
    try:
        result_type = "found_existing" if results else "no_results"
        report_id = results[0].report.id if results else None
        await search_session_service.record(
            db, space_id, body.query, source="api", result_type=result_type, report_id=report_id
        )
        await db.commit()
    except Exception:
        logger.warning("Failed to record search session", exc_info=True)
    return results


@router.post("/search/check", response_model=SearchCheckResponse)
async def check_duplicate(
    body: SearchCheckRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.read"),
):
    return await search_engine.check_duplicate(db, space_id, body.query, threshold=body.threshold)


# ======================== Topics ========================


@router.get("/topics", response_model=PaginatedResponse[TopicResponse])
async def list_topics(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.read"),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    return await topic_service.list_topics(db, space_id, pagination)


@router.post("/topics", response_model=TopicResponse, status_code=201)
async def create_topic(
    body: TopicCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.write"),
):
    result = await topic_service.create_topic(db, space_id, body)
    await db.commit()
    return result


@router.get("/topics/{topic_id}/related", response_model=list[TopicResponse])
async def get_related_topics(
    topic_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.read"),
):
    return await topic_service.get_related(db, topic_id)


@router.post("/topics/backfill")
async def backfill_topics(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.write"),
):
    """Backfill topics from all existing report tags. Idempotent."""
    result = await topic_service.backfill_all(db, space_id)
    await db.commit()
    return result


@router.get("/topics/graph", response_model=TopicGraphResponse)
async def get_topic_graph(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.read"),
):
    return await topic_service.get_graph(db, space_id)


# ======================== Dashboard ========================


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.read"),
):
    return await dashboard_service.get_summary(db, space_id)


@router.get("/dashboard/timeline", response_model=TimelineResponse)
async def get_timeline(
    space_id: str = Query("default"),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.read"),
):
    return await dashboard_service.get_timeline(db, space_id, days)


# ======================== Status ========================


@router.get("/status")
async def intelflow_status():
    return {"module": "intelflow", "status": "active"}


# ======================== Frozen Tier (Thaw) ========================


@router.get("/frozen/reports", summary="List frozen reports")
async def list_frozen_reports(
    space_id: str = Query("default"),
    tag: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.read"),
):
    """List frozen report metadata (no content -- needs thaw)."""
    from .models import ReportFrozen

    q = select(ReportFrozen).where(
        ReportFrozen.space_id == space_id,
    )
    if tag:
        q = q.where(ReportFrozen.tags.contains([tag]))

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.order_by(ReportFrozen.frozen_at.desc())
    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    return {
        "items": [
            {
                "id": r.id,
                "space_id": r.space_id,
                "created_at": r.created_at,
                "frozen_at": r.frozen_at,
                "title": r.title,
                "query": r.query,
                "tags": r.tags or [],
                "summary": r.summary,
                "skill_name": r.skill_name,
                "content_size": r.content_size,
                "tier": "frozen",
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get(
    "/frozen/reports/{report_id}/thaw",
    summary="Thaw frozen report",
)
async def thaw_frozen_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.read"),
):
    """Fetch full content from S3 for a frozen report.

    May take 1-3s for S3 download + decompression.
    """
    from .models import ReportFrozen

    q = select(ReportFrozen).where(
        ReportFrozen.id == report_id,
    )
    frozen = (await db.execute(q)).scalar_one_or_none()
    if not frozen:
        raise NotFoundError(
            f"Frozen report {report_id} not found",
            code="intelflow.frozen_not_found",
        )

    data = await download_and_decompress(frozen.s3_uri)
    if data is None:
        raise BadRequestError(
            "Failed to retrieve frozen content from S3",
            code="intelflow.thaw_failed",
        )

    # Verify integrity
    actual_hash = compute_content_hash(data)
    if actual_hash != frozen.content_hash:
        raise BadRequestError(
            f"Content hash mismatch: expected {frozen.content_hash}, got {actual_hash}",
            code="intelflow.integrity_error",
        )

    content = json.loads(data.decode("utf-8"))
    return {
        "id": report_id,
        "content": content,
        "tier": "frozen",
        "frozen_at": frozen.frozen_at,
    }


@router.get(
    "/frozen/briefings",
    summary="List frozen briefings",
)
async def list_frozen_briefings(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.read"),
):
    """List frozen briefing metadata (no content -- needs thaw)."""
    from .models import BriefingFrozen

    q = select(BriefingFrozen).where(
        BriefingFrozen.space_id == space_id,
    )

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.order_by(BriefingFrozen.frozen_at.desc())
    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    return {
        "items": [
            {
                "id": r.id,
                "space_id": r.space_id,
                "created_at": r.created_at,
                "frozen_at": r.frozen_at,
                "date": str(r.date) if r.date else None,
                "domain": r.domain,
                "tags": r.tags or [],
                "summary": r.summary,
                "content_size": r.content_size,
                "tier": "frozen",
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get(
    "/frozen/briefings/{briefing_id}/thaw",
    summary="Thaw frozen briefing",
)
async def thaw_frozen_briefing(
    briefing_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("intelflow.read"),
):
    """Fetch full content from S3 for a frozen briefing.

    May take 1-3s for S3 download + decompression.
    """
    from .models import BriefingFrozen

    q = select(BriefingFrozen).where(
        BriefingFrozen.id == briefing_id,
    )
    frozen = (await db.execute(q)).scalar_one_or_none()
    if not frozen:
        raise NotFoundError(
            f"Frozen briefing {briefing_id} not found",
            code="intelflow.frozen_not_found",
        )

    data = await download_and_decompress(frozen.s3_uri)
    if data is None:
        raise BadRequestError(
            "Failed to retrieve frozen content from S3",
            code="intelflow.thaw_failed",
        )

    # Verify integrity
    actual_hash = compute_content_hash(data)
    if actual_hash != frozen.content_hash:
        raise BadRequestError(
            f"Content hash mismatch: expected {frozen.content_hash}, got {actual_hash}",
            code="intelflow.integrity_error",
        )

    content = json.loads(data.decode("utf-8"))
    return {
        "id": briefing_id,
        "content": content,
        "tier": "frozen",
        "frozen_at": frozen.frozen_at,
    }
