"""API routes — event ingest, stats, admin."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import aiofiles
from auth import require_auth
from database import get_session
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from models import HookEvent
from schemas import (
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


# ──────────────────────────────────────────────
# Public endpoints (localhost only, no auth)
# ──────────────────────────────────────────────


@router.post("/api/events", status_code=202)
async def ingest_event(request: Request):
    """Accept event → write to spool → 202 Accepted.

    Does NOT write to DB directly. Spool drainer handles persistence.
    """
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
        total_events_processed=0,  # kept for API compat, real count from /api/stats/summary
        pending_files=len(spool_files),
    )


# ──────────────────────────────────────────────
# Authenticated endpoints (cookie auth)
# ──────────────────────────────────────────────


@router.get("/api/stats/summary")
async def stats_summary(
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
) -> SummaryStats:
    """Summary stats: total events, today count, unique sessions."""
    result = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE created_at > now() - interval '24 hours') AS today,
                COUNT(DISTINCT session_id) AS unique_sessions
            FROM hook_observatory.events
        """)
    )
    row = result.one()
    return SummaryStats(total=row.total, today=row.today, unique_sessions=row.unique_sessions)


@router.get("/api/stats/by-event")
async def stats_by_event(
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
) -> list[EventTypeStats]:
    """Event count grouped by event_type."""
    result = await db.execute(
        text("""
            SELECT event_type, COUNT(*) AS count,
                COUNT(*) FILTER (WHERE created_at > now() - interval '24 hours') AS today
            FROM hook_observatory.events
            GROUP BY event_type ORDER BY count DESC
        """)
    )
    return [EventTypeStats(event_type=r.event_type, count=r.count, today=r.today) for r in result.all()]


@router.get("/api/stats/by-tool")
async def stats_by_tool(
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
) -> list[ToolStats]:
    """Tool usage ranking."""
    result = await db.execute(
        text("""
            SELECT tool_name, COUNT(*) AS count
            FROM hook_observatory.events
            WHERE tool_name IS NOT NULL
            GROUP BY tool_name ORDER BY count DESC
            LIMIT :limit
        """),
        {"limit": limit},
    )
    return [ToolStats(tool_name=r.tool_name, count=r.count) for r in result.all()]


@router.get("/api/stats/by-session")
async def stats_by_session(
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
) -> list[SessionStats]:
    """Recent sessions with event counts."""
    result = await db.execute(
        text("""
            SELECT session_id, COUNT(*) AS event_count,
                MIN(created_at) AS first_seen, MAX(created_at) AS last_seen
            FROM hook_observatory.events
            WHERE session_id IS NOT NULL
            GROUP BY session_id
            ORDER BY last_seen DESC
            LIMIT :limit
        """),
        {"limit": limit},
    )
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
    """Time-series event counts in buckets."""
    # Parse range (e.g. "7d", "24h", "60m")
    unit_map = {"d": "days", "h": "hours", "m": "minutes"}
    amount = int(range[:-1])
    unit = unit_map.get(range[-1], "days")
    interval = f"{amount} {unit}"

    result = await db.execute(
        text(f"""
            SELECT date_trunc(:granularity, created_at) AS bucket,
                COUNT(*) AS count
            FROM hook_observatory.events
            WHERE created_at > now() - interval '{interval}'
            GROUP BY bucket ORDER BY bucket
        """),
        {"granularity": granularity},
    )
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
