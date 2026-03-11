"""Invocation recording routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from db import Invocation, get_session
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
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

    model_config = {"from_attributes": True}


class InvocationListResponse(BaseModel):
    items: list[InvocationResponse]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/invocations", status_code=201)
async def record_invocation(
    body: InvocationCreateRequest,
    db: AsyncSession = Depends(get_session),
) -> InvocationResponse:
    """Record a skill invocation (from hook telemetry)."""
    inv = Invocation(**body.model_dump())
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

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    result = await db.execute(query.offset(offset).limit(limit))
    items = [InvocationResponse.model_validate(i) for i in result.scalars().all()]

    return InvocationListResponse(items=items, total=total, limit=limit, offset=offset)
