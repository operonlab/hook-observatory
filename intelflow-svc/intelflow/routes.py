"""Intelflow routes — REST API endpoints for standalone intelflow-svc.

Simplified from core/src/modules/intelflow/routes.py:
- No auth middleware (standalone service, auth handled at gateway)
- No embedding generation (Qdrant not available in standalone)
- No semantic search (requires Qdrant) — replaced with text search
- No frozen tier endpoints (require S3/RustFS)
- No synthesis endpoint (requires RLM engine)
- No GRC routes (require grc framework)
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database import get_db
from shared.errors import NotFoundError
from shared.schemas import PaginatedResponse, PaginationParams

from . import search as search_engine
from .schemas import (
    DashboardResponse,
    ReportCreate,
    ReportResponse,
    ReportUpdate,
    TextSearchRequest,
    TextSearchResult,
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
):
    instance = await report_service.get(db, report_id)
    if not instance:
        raise NotFoundError("Report not found", code="intelflow.report_not_found")
    return report_service.to_response(instance)


@router.post("/reports", response_model=ReportResponse, status_code=201)
async def create_report(
    body: ReportCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    # Strip skill_name from tags to avoid pollution
    if body.skill_name and body.tags:
        skip_tag = body.skill_name.strip().lower()
        body.tags = [t for t in body.tags if t.strip().lower() != skip_tag]
    instance = await report_service.create(db, space_id, body)
    # Override created_at if provided (for migration)
    if body.created_at:
        instance.created_at = body.created_at
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
):
    deleted = await report_service.delete(db, report_id)
    if not deleted:
        raise NotFoundError("Report not found", code="intelflow.report_not_found")
    await db.commit()


# ======================== Text Search ========================


@router.post("/search", response_model=list[TextSearchResult])
async def search_reports(
    body: TextSearchRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    results = await search_engine.text_search(db, space_id, body.query, limit=body.limit)
    # Record search session (non-critical)
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


# ======================== Topics ========================


@router.get("/topics", response_model=PaginatedResponse[TopicResponse])
async def list_topics(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    return await topic_service.list_topics(db, space_id, pagination)


@router.post("/topics", response_model=TopicResponse, status_code=201)
async def create_topic(
    body: TopicCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    result = await topic_service.create_topic(db, space_id, body)
    await db.commit()
    return result


@router.get("/topics/{topic_id}/related", response_model=list[TopicResponse])
async def get_related_topics(
    topic_id: str,
    db: AsyncSession = Depends(get_db),
):
    return await topic_service.get_related(db, topic_id)


@router.post("/topics/backfill")
async def backfill_topics(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    """Backfill topics from all existing report tags. Idempotent."""
    result = await topic_service.backfill_all(db, space_id)
    await db.commit()
    return result


@router.get("/topics/graph", response_model=TopicGraphResponse)
async def get_topic_graph(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    return await topic_service.get_graph(db, space_id)


# ======================== Dashboard ========================


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    return await dashboard_service.get_summary(db, space_id)


@router.get("/dashboard/timeline", response_model=TimelineResponse)
async def get_timeline(
    space_id: str = Query("default"),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    return await dashboard_service.get_timeline(db, space_id, days)


# ======================== Status ========================


@router.get("/status")
async def intelflow_status():
    return {"module": "intelflow", "status": "active", "service": "intelflow-svc"}
