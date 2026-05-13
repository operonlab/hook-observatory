"""API routes — event ingest, stats, admin."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import aiofiles
from auth import require_auth
from database import IS_POSTGRES, get_session
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from models import HookEvent
from schemas import (
    AllStats,
    EventListResponse,
    EventResponse,
    EventTypeStats,
    HealthResponse,
    SessionStats,
    SummaryStats,
    TimelineBucket,
    ToolStats,
)
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import config

router = APIRouter()

# ── SQL helpers ──────────────────────────────────────────────────

_T = "hook_observatory.events" if IS_POSTGRES else "events"


def _count_filter(condition: str) -> str:
    """COUNT with filter — PostgreSQL FILTER vs SQLite CASE."""
    if IS_POSTGRES:
        return f"COUNT(*) FILTER (WHERE {condition})"
    return f"SUM(CASE WHEN {condition} THEN 1 ELSE 0 END)"


def _recent_condition(hours: int = 24) -> str:
    """WHERE clause for recent events."""
    if IS_POSTGRES:
        return f"created_at > now() - interval '{hours} hours'"
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    return f"created_at > '{cutoff}'"


def _date_trunc(granularity: str, column: str) -> str:
    """date_trunc for PostgreSQL, strftime for SQLite."""
    if IS_POSTGRES:
        return f"date_trunc('{granularity}', {column})"
    fmt_map = {"hour": "%Y-%m-%d %H:00:00", "day": "%Y-%m-%d", "minute": "%Y-%m-%d %H:%M:00"}
    return f"strftime('{fmt_map.get(granularity, '%Y-%m-%d %H:00:00')}', {column})"


# ──────────────────────────────────────────────
# Public endpoints (localhost only, no auth)
# ──────────────────────────────────────────────


@router.post("/api/events", status_code=202)
async def ingest_event(request: Request):
    """Accept event → write to spool → 202 Accepted."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid_json"})

    spool_path = config.spool_dir / "events.jsonl"
    event_type = body.get("event_type", body.get("hook_event_name", "api"))
    ts = datetime.now(UTC).isoformat()
    line = json.dumps({"event_type": event_type, "ts": ts, "data": body})

    try:
        async with aiofiles.open(spool_path, "a") as f:
            await f.write(line + "\n")
        return {"status": "accepted"}
    except OSError:
        return JSONResponse(status_code=503, content={"error": "spool_write_failed"})


@router.get("/api/health")
async def health():
    """Health check — no auth required."""
    spool_files = list(config.spool_dir.glob("*.jsonl")) + list(config.spool_dir.glob("*.draining"))
    return HealthResponse(
        status="ok",
        spool_dir=str(config.spool_dir),
        total_events_processed=0,
        pending_files=len(spool_files),
    )


# ──────────────────────────────────────────────
# Authenticated endpoints (cookie auth)
# ──────────────────────────────────────────────


def _summary_sql() -> str:
    today_filter = _count_filter(_recent_condition(24))
    return f"""
        SELECT COUNT(*) AS total,
            {today_filter} AS today,
            COUNT(DISTINCT session_id) AS unique_sessions
        FROM {_T}
    """


def _by_event_sql() -> str:
    today_filter = _count_filter(_recent_condition(24))
    return f"""
        SELECT event_type, COUNT(*) AS count, {today_filter} AS today
        FROM {_T}
        GROUP BY event_type ORDER BY count DESC
    """


def _by_tool_sql() -> str:
    return f"""
        SELECT tool_name, COUNT(*) AS count
        FROM {_T}
        WHERE tool_name IS NOT NULL
        GROUP BY tool_name ORDER BY count DESC
        LIMIT :limit
    """


def _by_session_sql() -> str:
    return f"""
        SELECT session_id, COUNT(*) AS event_count,
            MIN(created_at) AS first_seen, MAX(created_at) AS last_seen
        FROM {_T}
        WHERE session_id IS NOT NULL
        GROUP BY session_id
        ORDER BY last_seen DESC
        LIMIT :limit
    """


def _timeline_sql(granularity: str, days: int, hours: int, mins: int) -> tuple[str, dict]:
    bucket_expr = _date_trunc(granularity, "created_at")
    if IS_POSTGRES:
        return (
            f"""
            SELECT {bucket_expr} AS bucket, COUNT(*) AS count
            FROM {_T}
            WHERE created_at > now() - make_interval(
                days => :days, hours => :hours, mins => :mins
            )
            GROUP BY bucket ORDER BY bucket
            """,
            {"days": days, "hours": hours, "mins": mins},
        )
    else:
        cutoff = (datetime.now(UTC) - timedelta(days=days, hours=hours, minutes=mins)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        return (
            f"""
            SELECT {bucket_expr} AS bucket, COUNT(*) AS count
            FROM {_T}
            WHERE created_at > :cutoff
            GROUP BY bucket ORDER BY bucket
            """,
            {"cutoff": cutoff},
        )


@router.get("/api/stats/summary")
async def stats_summary(
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
) -> SummaryStats:
    result = await db.execute(text(_summary_sql()))
    row = result.one()
    return SummaryStats(
        total=row.total, today=int(row.today or 0), unique_sessions=row.unique_sessions
    )


@router.get("/api/stats/all")
async def stats_all(
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
) -> AllStats:
    summary_r = await db.execute(text(_summary_sql()))
    event_r = await db.execute(text(_by_event_sql()))
    tool_r = await db.execute(text(_by_tool_sql()), {"limit": 20})
    session_r = await db.execute(text(_by_session_sql()), {"limit": 20})

    tl_sql, tl_params = _timeline_sql("hour", days=7, hours=0, mins=0)
    timeline_r = await db.execute(text(tl_sql), tl_params)

    row = summary_r.one()
    return AllStats(
        summary=SummaryStats(
            total=row.total, today=int(row.today or 0), unique_sessions=row.unique_sessions
        ),
        by_event=[
            EventTypeStats(event_type=r.event_type, count=r.count, today=int(r.today or 0))
            for r in event_r.all()
        ],
        by_tool=[ToolStats(tool_name=r.tool_name, count=r.count) for r in tool_r.all()],
        sessions=[
            SessionStats(
                session_id=r.session_id,
                event_count=r.event_count,
                first_seen=r.first_seen,
                last_seen=r.last_seen,
            )
            for r in session_r.all()
        ],
        timeline=[TimelineBucket(bucket=r.bucket, count=r.count) for r in timeline_r.all()],
    )


@router.get("/api/stats/by-event")
async def stats_by_event(
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
) -> list[EventTypeStats]:
    result = await db.execute(text(_by_event_sql()))
    return [
        EventTypeStats(event_type=r.event_type, count=r.count, today=int(r.today or 0))
        for r in result.all()
    ]


@router.get("/api/stats/by-tool")
async def stats_by_tool(
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
) -> list[ToolStats]:
    result = await db.execute(text(_by_tool_sql()), {"limit": limit})
    return [ToolStats(tool_name=r.tool_name, count=r.count) for r in result.all()]


@router.get("/api/stats/by-session")
async def stats_by_session(
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
) -> list[SessionStats]:
    result = await db.execute(text(_by_session_sql()), {"limit": limit})
    return [
        SessionStats(
            session_id=r.session_id,
            event_count=r.event_count,
            first_seen=r.first_seen,
            last_seen=r.last_seen,
        )
        for r in result.all()
    ]


@router.get("/api/stats/timeline")
async def stats_timeline(
    range: str = Query("7d", pattern=r"^\d+[dhm]$"),
    granularity: str = Query("hour", pattern=r"^(hour|day|minute)$"),
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
) -> list[TimelineBucket]:
    amount = int(range[:-1])
    unit_key = range[-1]
    days = amount if unit_key == "d" else 0
    hours = amount if unit_key == "h" else 0
    mins = amount if unit_key == "m" else 0

    tl_sql, tl_params = _timeline_sql(granularity, days, hours, mins)
    result = await db.execute(text(tl_sql), tl_params)
    return [TimelineBucket(bucket=r.bucket, count=r.count) for r in result.all()]


@router.get("/api/events")
async def list_events(
    event_type: str | None = Query(None),
    session_id: str | None = Query(None),
    tool_name: str | None = Query(None),
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
) -> EventListResponse:
    """Paginated event list with filters."""
    query = select(HookEvent).order_by(HookEvent.created_at.desc())
    count_query = select(func.count()).select_from(HookEvent)

    if event_type:
        query = query.where(HookEvent.event_type == event_type)
        count_query = count_query.where(HookEvent.event_type == event_type)
    if session_id:
        query = query.where(HookEvent.session_id == session_id)
        count_query = count_query.where(HookEvent.session_id == session_id)
    if tool_name:
        query = query.where(HookEvent.tool_name == tool_name)
        count_query = count_query.where(HookEvent.tool_name == tool_name)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    result = await db.execute(query.offset(offset).limit(limit))
    items = [
        EventResponse(
            id=str(e.id),
            event_type=e.event_type,
            session_id=e.session_id,
            cwd=e.cwd,
            tool_name=e.tool_name,
            hook_name=e.hook_name,
            payload=e.payload,
            created_at=e.created_at,
        )
        for e in result.scalars().all()
    ]

    return EventListResponse(items=items, total=total, limit=limit, offset=offset)
