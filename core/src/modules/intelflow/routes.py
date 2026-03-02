"""Intelflow routes — REST API endpoints.

Prefix: /api/intelflow (mounted in main.py)
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db
from src.shared.embedding import get_embedding
from src.shared.errors import NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams

from . import search as search_engine
from .schemas import (
    BriefingCreate,
    BriefingResponse,
    BriefingSubtopicCreate,
    BriefingSubtopicResponse,
    BriefingSubtopicUpdate,
    BriefingTopicCreate,
    BriefingTopicResponse,
    BriefingTopicUpdate,
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
    briefing_service,
    briefing_topic_service,
    dashboard_service,
    report_service,
    search_session_service,
    topic_service,
)

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
):
    # Strip skill_name from tags to avoid pollution
    if body.skill_name and body.tags:
        skip_tag = body.skill_name.strip().lower()
        body.tags = [t for t in body.tags if t.strip().lower() != skip_tag]
    instance = await report_service.create(db, space_id, body)
    # Override created_at if provided (for migration)
    if body.created_at:
        instance.created_at = body.created_at
    # Generate embedding (best-effort) — write to both inline column and sub-table
    embedding = await get_embedding(f"{instance.title} {instance.query}")
    if embedding:
        instance.embedding = embedding
        from .models import ReportEmbedding

        db.add(ReportEmbedding(report_id=instance.id, embedding=embedding))
    await db.commit()
    await db.refresh(instance)
    # Extract topics from tags
    if instance.tags:
        await topic_service.extract_from_report(db, instance)
    # Record search session
    await search_session_service.record(
        db,
        space_id,
        body.query,
        source=body.skill_name,
        result_type="new_report",
        report_id=instance.id,
    )
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


# ======================== Search ========================


@router.post("/search", response_model=list[SemanticSearchResult])
async def search_reports(
    body: SearchRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    results = await search_engine.semantic_search(
        db, space_id, body.query, limit=body.limit, threshold=body.threshold
    )
    # Record search session
    result_type = "found_existing" if results else "no_results"
    report_id = results[0].report.id if results else None
    await search_session_service.record(
        db, space_id, body.query, source="api", result_type=result_type, report_id=report_id
    )
    await db.commit()
    return results


@router.post("/search/check", response_model=SearchCheckResponse)
async def check_duplicate(
    body: SearchCheckRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    return await search_engine.check_duplicate(db, space_id, body.query, threshold=body.threshold)


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


# ======================== Briefing Topics (Management) ========================


@router.get("/briefings/topics", response_model=PaginatedResponse[BriefingTopicResponse])
async def list_briefing_topics(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    return await briefing_topic_service.list(db, space_id, pagination)


@router.post("/briefings/topics", response_model=BriefingTopicResponse, status_code=201)
async def create_briefing_topic(
    body: BriefingTopicCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    instance = await briefing_topic_service.create(db, space_id, body)
    await db.commit()
    return briefing_topic_service.to_response(instance)


@router.put("/briefings/topics/{topic_id}", response_model=BriefingTopicResponse)
async def update_briefing_topic(
    topic_id: str,
    body: BriefingTopicUpdate,
    db: AsyncSession = Depends(get_db),
):
    instance = await briefing_topic_service.update(db, topic_id, body)
    if not instance:
        raise NotFoundError("Briefing topic not found", code="intelflow.briefing_topic_not_found")
    await db.commit()
    return briefing_topic_service.to_response(instance)


@router.delete("/briefings/topics/{topic_id}", status_code=204)
async def delete_briefing_topic(
    topic_id: str,
    db: AsyncSession = Depends(get_db),
):
    deleted = await briefing_topic_service.delete(db, topic_id)
    if not deleted:
        raise NotFoundError("Briefing topic not found", code="intelflow.briefing_topic_not_found")
    await db.commit()


@router.patch("/briefings/topics/{topic_id}/toggle", response_model=BriefingTopicResponse)
async def toggle_briefing_topic(
    topic_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await briefing_topic_service.toggle(db, topic_id)
    await db.commit()
    return result


@router.post(
    "/briefings/topics/{topic_id}/subtopics",
    response_model=BriefingSubtopicResponse,
    status_code=201,
)
async def add_subtopic(
    topic_id: str,
    body: BriefingSubtopicCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    result = await briefing_topic_service.add_subtopic(db, topic_id, space_id, body)
    await db.commit()
    return result


@router.put(
    "/briefings/topics/{topic_id}/subtopics/{subtopic_id}",
    response_model=BriefingSubtopicResponse,
)
async def update_subtopic(
    topic_id: str,
    subtopic_id: str,
    body: BriefingSubtopicUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await briefing_topic_service.update_subtopic(db, subtopic_id, body)
    await db.commit()
    return result


@router.delete("/briefings/topics/{topic_id}/subtopics/{subtopic_id}", status_code=204)
async def delete_subtopic(
    topic_id: str,
    subtopic_id: str,
    db: AsyncSession = Depends(get_db),
):
    deleted = await briefing_topic_service.delete_subtopic(db, subtopic_id)
    if not deleted:
        raise NotFoundError("Subtopic not found", code="intelflow.subtopic_not_found")
    await db.commit()


# ======================== Briefings ========================


@router.get("/briefings", response_model=PaginatedResponse[BriefingResponse])
async def list_briefings(
    space_id: str = Query("default"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    topic_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    return await briefing_service.list_briefings(
        db, space_id, date_from, date_to, topic_id, pagination
    )


@router.get("/briefings/{target_date}", response_model=list[BriefingResponse])
async def get_briefings_by_date(
    target_date: date,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    return await briefing_service.get_by_date(db, space_id, target_date)


@router.get("/briefings/{target_date}/{domain}", response_model=BriefingResponse)
async def get_briefing_by_date_and_domain(
    target_date: date,
    domain: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    result = await briefing_service.get_by_date_and_topic(db, space_id, target_date, domain)
    if not result:
        raise NotFoundError("Briefing not found", code="intelflow.briefing_not_found")
    return result


@router.post("/briefings", response_model=BriefingResponse, status_code=201)
async def create_briefing(
    body: BriefingCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    result = await briefing_service.create_briefing(db, space_id, body)
    await db.commit()
    return result


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
    return {"module": "intelflow", "status": "active"}
