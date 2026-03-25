"""Invocation recording routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from classify import classify
from db import Invocation, get_session
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from services.attribution import AttributionService
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class InvocationCreateRequest(BaseModel):
    skill_name: str
    duration_ms: int | None = None
    success: bool = True
    error_message: str | None = None
    tool_calls_count: int = 0
    session_id: str | None = None
    agent_model: str | None = None
    payload: dict[str, Any] | None = None
    tool_use_id: str | None = None
    timestamp: datetime | None = None
    category: str | None = None
    manual_estimate_minutes: float | None = None
    time_saved_minutes: float | None = None


class InvocationResponse(BaseModel):
    id: str
    skill_name: str
    timestamp: datetime
    duration_ms: int | None
    success: bool
    error_message: str | None
    tool_calls_count: int
    session_id: str | None
    agent_model: str | None
    payload: dict[str, Any] | None
    tool_use_id: str | None
    category: str
    manual_estimate_minutes: float | None = None
    time_saved_minutes: float | None = None

    model_config = {"from_attributes": True}


class InvocationListResponse(BaseModel):
    items: list[InvocationResponse]
    total: int
    limit: int
    offset: int


class AttributionItem(BaseModel):
    invocation_id: str
    skill_name: str
    attribution_score: float
    attribution_reason: str


class AttributionResponse(BaseModel):
    session_id: str
    attributions: list[AttributionItem]
    total_failures: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/invocations", status_code=201)
async def record_invocation(
    body: InvocationCreateRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> InvocationResponse:
    """Record a skill invocation (from hook telemetry)."""
    # Dedup by tool_use_id if provided
    if body.tool_use_id:
        existing = await db.execute(
            select(Invocation).where(Invocation.tool_use_id == body.tool_use_id)
        )
        found = existing.scalar_one_or_none()
        if found:
            response.status_code = 200
            return InvocationResponse.model_validate(found)

    data = body.model_dump()
    # Strip None timestamp so DB server_default applies for real-time calls
    if data.get("timestamp") is None:
        data.pop("timestamp", None)
    # Auto-classify if not explicitly provided
    if not data.get("category"):
        data["category"] = classify(data["skill_name"])
    inv = Invocation(**data)
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    return InvocationResponse.model_validate(inv)


@router.get("/invocations")
async def list_invocations(
    skill_name: str | None = Query(None),
    session_id: str | None = Query(None),
    success: bool | None = Query(None),
    since: datetime | None = Query(None, description="Start of date range (ISO 8601)"),
    until: datetime | None = Query(None, description="End of date range (ISO 8601)"),
    category: str | None = Query(
        None, description="Filter by category (skill, command, test, unknown)"
    ),
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> InvocationListResponse:
    """List invocations with filters."""
    query = select(Invocation).order_by(Invocation.timestamp.desc())
    count_query = select(func.count()).select_from(Invocation)

    if skill_name:
        query = query.where(Invocation.skill_name == skill_name)
        count_query = count_query.where(Invocation.skill_name == skill_name)
    if session_id:
        query = query.where(Invocation.session_id == session_id)
        count_query = count_query.where(Invocation.session_id == session_id)
    if success is not None:
        query = query.where(Invocation.success == success)
        count_query = count_query.where(Invocation.success == success)
    if since:
        query = query.where(Invocation.timestamp >= since)
        count_query = count_query.where(Invocation.timestamp >= since)
    if until:
        query = query.where(Invocation.timestamp <= until)
        count_query = count_query.where(Invocation.timestamp <= until)
    if category:
        query = query.where(Invocation.category == category)
        count_query = count_query.where(Invocation.category == category)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    result = await db.execute(query.offset(offset).limit(limit))
    items = [InvocationResponse.model_validate(i) for i in result.scalars().all()]

    return InvocationListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/invocations/attribute/{session_id}")
async def attribute_session(
    session_id: str,
    db: AsyncSession = Depends(get_session),
) -> AttributionResponse:
    """Compute failure attribution for a session's failed invocations."""
    svc = AttributionService(db)
    attributions = await svc.attribute_session(session_id)
    return AttributionResponse(
        session_id=session_id,
        attributions=attributions,
        total_failures=len(attributions),
    )


@router.get("/invocations/attribution/{session_id}")
async def get_attribution(
    session_id: str,
    db: AsyncSession = Depends(get_session),
) -> AttributionResponse:
    """Get existing attribution results for a session."""
    result = await db.execute(
        select(Invocation).where(
            Invocation.session_id == session_id,
            Invocation.attribution_score.isnot(None),
        )
    )
    items = result.scalars().all()
    attributions = [
        AttributionItem(
            invocation_id=i.id,
            skill_name=i.skill_name,
            attribution_score=i.attribution_score,
            attribution_reason=i.attribution_reason or "",
        )
        for i in items
    ]
    return AttributionResponse(
        session_id=session_id,
        attributions=attributions,
        total_failures=len(attributions),
    )
