"""Briefing API routes — /api/briefing/*"""

import subprocess
from datetime import date
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from src.shared.deps import get_current_user, get_db, require_permission
from src.shared.errors import NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams

from .models import BriefingFrozen
from .schemas import (
    AnalystCreate,
    AnalystResponse,
    AnalystUpdate,
    BriefingCreate,
    BriefingEntryCreate,
    BriefingEntryResponse,
    BriefingResponse,
    BriefingSubtopicCreate,
    BriefingSubtopicResponse,
    BriefingSubtopicUpdate,
    BriefingTopicCreate,
    BriefingTopicResponse,
    BriefingTopicUpdate,
    BriefingUpdate,
    DailySummaryResponse,
    FollowUpCreate,
    FollowUpResponse,
)
from .services import analyst_service, briefing_service, briefing_topic_service, follow_up_service
from .streaming import briefing_stream_generator

router = APIRouter()


# ======================== Streaming ========================


@router.get("/entries/{entry_id}/stream")
async def stream_entry_generation(
    entry_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventSourceResponse:
    """SSE stream for a single entry's generation progress.

    Subscribes to ``briefing:stream:{entry_id}`` and relays blocks to the
    client as Server-Sent Events.  The stream terminates when a ``done``
    block is published or after 5 minutes of inactivity.
    """
    return EventSourceResponse(briefing_stream_generator(entry_id))


@router.get("/daily/{date}/stream")
async def stream_daily_briefing(
    date: str,
    space_id: str = Query("default"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventSourceResponse:
    """SSE stream for an entire daily briefing generation.

    The ``date`` path parameter is treated as a logical stream identifier so
    callers can subscribe before the briefing generator starts.  Publishers
    should use a ``briefing_id`` equal to ``{space_id}:{date}`` or any agreed
    key; clients must ensure they use the same value when constructing the URL.
    """
    stream_id = f"{space_id}:{date}"
    return EventSourceResponse(briefing_stream_generator(stream_id))


# ======================== Topics ========================


@router.get("/topics", response_model=PaginatedResponse[BriefingTopicResponse])
async def list_topics(
    page: int = 1,
    page_size: int = 50,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.read"),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    return await briefing_topic_service.list(db, space_id, pagination)


@router.post("/topics", response_model=BriefingTopicResponse, status_code=201)
async def create_topic(
    body: BriefingTopicCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.write"),
):
    instance = await briefing_topic_service.create(db, space_id, body)
    await db.commit()
    return briefing_topic_service.to_response(instance)


@router.put("/topics/{topic_id}", response_model=BriefingTopicResponse)
async def update_topic(
    topic_id: str,
    body: BriefingTopicUpdate,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.write"),
):
    instance = await briefing_topic_service.update(db, topic_id, body)
    if not instance:
        raise NotFoundError("Briefing topic not found", code="briefing.topic_not_found")
    await db.commit()
    return briefing_topic_service.to_response(instance)


@router.delete("/topics/{topic_id}", status_code=204)
async def delete_topic(
    topic_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.write"),
):
    deleted = await briefing_topic_service.delete(db, topic_id)
    if not deleted:
        raise NotFoundError("Briefing topic not found", code="briefing.topic_not_found")
    await db.commit()


@router.patch("/topics/{topic_id}/toggle", response_model=BriefingTopicResponse)
async def toggle_topic(
    topic_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.write"),
):
    result = await briefing_topic_service.toggle(db, topic_id)
    await db.commit()
    return result


# ======================== Subtopics ========================


@router.post(
    "/topics/{topic_id}/subtopics",
    response_model=BriefingSubtopicResponse,
    status_code=201,
)
async def create_subtopic(
    topic_id: str,
    body: BriefingSubtopicCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.write"),
):
    result = await briefing_topic_service.add_subtopic(db, topic_id, space_id, body)
    await db.commit()
    return result


@router.put(
    "/topics/{topic_id}/subtopics/{subtopic_id}",
    response_model=BriefingSubtopicResponse,
)
async def update_subtopic(
    subtopic_id: str,
    body: BriefingSubtopicUpdate,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.write"),
):
    result = await briefing_topic_service.update_subtopic(db, subtopic_id, body)
    await db.commit()
    return result


@router.delete("/topics/{topic_id}/subtopics/{subtopic_id}", status_code=204)
async def delete_subtopic(
    subtopic_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.write"),
):
    deleted = await briefing_topic_service.delete_subtopic(db, subtopic_id)
    if not deleted:
        raise NotFoundError("Subtopic not found", code="briefing.subtopic_not_found")
    await db.commit()


# ======================== Analysts ========================


@router.get("/analysts", response_model=list[AnalystResponse])
async def list_analysts(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.read"),
):
    pagination = PaginationParams(page=1, page_size=100)
    result = await analyst_service.list(db, space_id, pagination)
    return result.items


@router.post("/analysts", response_model=AnalystResponse, status_code=201)
async def create_analyst(
    body: AnalystCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.write"),
):
    instance = await analyst_service.create(db, space_id, body)
    await db.commit()
    return analyst_service.to_response(instance)


@router.put("/analysts/{analyst_id}", response_model=AnalystResponse)
async def update_analyst(
    analyst_id: str,
    body: AnalystUpdate,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.write"),
):
    instance = await analyst_service.update(db, analyst_id, body)
    if not instance:
        raise NotFoundError("Analyst not found", code="briefing.analyst_not_found")
    await db.commit()
    return analyst_service.to_response(instance)


@router.delete("/analysts/{analyst_id}", status_code=204)
async def delete_analyst(
    analyst_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.write"),
):
    deleted = await analyst_service.delete(db, analyst_id)
    if not deleted:
        raise NotFoundError("Analyst not found", code="briefing.analyst_not_found")
    await db.commit()


@router.patch("/analysts/{analyst_id}/toggle", response_model=AnalystResponse)
async def toggle_analyst(
    analyst_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.write"),
):
    result = await analyst_service.toggle(db, analyst_id)
    await db.commit()
    return result


# ======================== Briefings ========================


@router.get("/daily", response_model=PaginatedResponse[BriefingResponse])
async def list_briefings(
    page: int = 1,
    page_size: int = 20,
    date_from: date | None = None,
    date_to: date | None = None,
    topic_id: str | None = None,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.read"),
):
    return await briefing_service.list_briefings(
        db, space_id, date_from, date_to, topic_id, PaginationParams(page=page, page_size=page_size)
    )


@router.get("/daily/{target_date}", response_model=list[BriefingResponse])
async def get_briefings_by_date(
    target_date: date,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.read"),
):
    return await briefing_service.get_by_date(db, space_id, target_date)


@router.get("/daily/{target_date}/summary", response_model=DailySummaryResponse)
async def get_daily_summary(
    target_date: date,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.read"),
):
    return await briefing_service.get_daily_summary(db, space_id, target_date)


@router.get("/daily/{target_date}/{domain}", response_model=BriefingResponse)
async def get_briefing_by_domain(
    target_date: date,
    domain: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.read"),
):
    result = await briefing_service.get_by_date_and_topic(db, space_id, target_date, domain)
    if not result:
        raise NotFoundError("Briefing not found", code="briefing.not_found")
    return result


@router.post("/daily", response_model=BriefingResponse, status_code=201)
async def create_briefing(
    body: BriefingCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.write"),
):
    result = await briefing_service.create_briefing(db, space_id, body)
    await db.commit()
    return result


@router.patch("/daily/{briefing_id}", response_model=BriefingResponse)
async def update_briefing_status(
    briefing_id: str,
    body: BriefingUpdate,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.write"),
):
    result = await briefing_service.update_status(db, briefing_id, body)
    await db.commit()
    return result


# ======================== Entries ========================


@router.get(
    "/daily/{briefing_id}/entries",
    response_model=list[BriefingEntryResponse],
)
async def list_entries(
    briefing_id: str,
    phase: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.read"),
):
    return await briefing_service.get_entries(db, briefing_id, phase)


@router.post(
    "/daily/{briefing_id}/entries",
    response_model=BriefingEntryResponse,
    status_code=201,
)
async def add_entry(
    briefing_id: str,
    body: BriefingEntryCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.write"),
):
    result = await briefing_service.add_entry(db, briefing_id, space_id, body)
    await db.commit()
    return result


# ======================== Follow-Ups ========================


@router.get(
    "/daily/{briefing_id}/follow-ups",
    response_model=list[FollowUpResponse],
)
async def list_follow_ups(
    briefing_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.read"),
):
    return await follow_up_service.list_follow_ups(db, briefing_id)


@router.post(
    "/daily/{briefing_id}/follow-ups",
    response_model=FollowUpResponse,
    status_code=201,
)
async def create_follow_up(
    briefing_id: str,
    body: FollowUpCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.write"),
):
    result = await follow_up_service.create_follow_up(db, briefing_id, space_id, body)
    await db.commit()
    return result


@router.post(
    "/follow-ups/{follow_up_id}/answer",
    response_model=FollowUpResponse,
)
async def answer_follow_up(
    follow_up_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.write"),
):
    result = await follow_up_service.answer_follow_up(db, follow_up_id, space_id)
    await db.commit()
    return result


# ======================== Trigger / Run Status ========================


@router.post("/trigger", status_code=202)
async def trigger_generation(
    background_tasks: BackgroundTasks,
    _user: dict = require_permission("briefing.write"),
):
    """Trigger daily briefing generation via run.py subprocess."""
    import os

    run_py = Path.home() / ".claude" / "scripts" / "daily-briefing" / "run.py"
    if not run_py.exists():
        raise NotFoundError("run.py not found", code="briefing.run_script_not_found")

    env = os.environ.copy()
    env["PATH"] = f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:{env.get('PATH', '')}"

    def _run():
        subprocess.Popen(  # noqa: S603
            [str(Path.home() / ".local/bin/python3"), str(run_py)],
            env=env,
            start_new_session=True,
        )

    background_tasks.add_task(_run)
    return {"status": "triggered"}


@router.get("/run-status")
async def get_run_status(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.read"),
):
    """Infer current run status from today's briefing records."""
    today = date.today()
    briefings = await briefing_service.get_by_date(db, space_id, today)
    if not briefings:
        return {"status": "idle", "date": today.isoformat(), "topics": []}

    statuses = [b.status for b in briefings]
    if all(s == "completed" for s in statuses):
        overall = "completed"
    elif any(s == "failed" for s in statuses):
        overall = "failed"
    elif any(s in ("searching", "analyzing", "debating", "synthesizing") for s in statuses):
        overall = "running"
    else:
        overall = "idle"

    return {
        "status": overall,
        "date": today.isoformat(),
        "topics": [
            {"domain": b.domain, "status": b.status, "id": b.id}
            for b in briefings
        ],
    }


# ======================== Frozen ========================


@router.get("/frozen", summary="List frozen briefings")
async def list_frozen_briefings(
    page: int = 1,
    page_size: int = 20,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.read"),
):
    from sqlalchemy import select as sa_select

    q = (
        sa_select(BriefingFrozen)
        .where(BriefingFrozen.space_id == space_id)
        .order_by(BriefingFrozen.frozen_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": r.id,
            "date": str(r.date) if r.date else None,
            "domain": r.domain,
            "summary": r.summary,
            "frozen_at": r.frozen_at,
            "content_size": r.content_size,
        }
        for r in rows
    ]


@router.get("/frozen/{briefing_id}/thaw", summary="Thaw frozen briefing")
async def thaw_frozen_briefing(
    briefing_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("briefing.read"),
):
    from sqlalchemy import select as sa_select

    from src.shared.storage import thaw_frozen_content

    q = sa_select(BriefingFrozen).where(BriefingFrozen.id == briefing_id)
    row = (await db.execute(q)).scalar_one_or_none()
    if not row:
        raise NotFoundError(
            f"Frozen briefing {briefing_id} not found",
            code="briefing.frozen_not_found",
        )

    content = await thaw_frozen_content(row.s3_uri, row.content_hash)
    return {
        "id": briefing_id,
        "date": str(row.date) if row.date else None,
        "domain": row.domain,
        "content": content,
    }
