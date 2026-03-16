"""Intent recording routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from db import Intent, get_session
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


class IntentCreateRequest(BaseModel):
    skill_name: str
    session_id: str | None = None
    timestamp: datetime | None = None
    payload: dict[str, Any] | None = None


class IntentResponse(BaseModel):
    id: str
    skill_name: str
    timestamp: datetime
    session_id: str | None
    payload: dict[str, Any] | None

    model_config = {"from_attributes": True}


class IntentListResponse(BaseModel):
    items: list[IntentResponse]
    total: int
    limit: int
    offset: int


@router.post("/intents", status_code=201)
async def record_intent(
    body: IntentCreateRequest,
    db: AsyncSession = Depends(get_session),
) -> IntentResponse:
    """Record a user skill intent (from UserPromptSubmit hook)."""
    data = body.model_dump()
    if data.get("timestamp") is None:
        data.pop("timestamp", None)
    intent = Intent(**data)
    db.add(intent)
    await db.commit()
    await db.refresh(intent)
    return IntentResponse.model_validate(intent)


@router.get("/intents")
async def list_intents(
    skill_name: str | None = Query(None),
    session_id: str | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> IntentListResponse:
    """List intents with filters."""
    query = select(Intent).order_by(Intent.timestamp.desc())
    count_query = select(func.count()).select_from(Intent)

    if skill_name:
        query = query.where(Intent.skill_name == skill_name)
        count_query = count_query.where(Intent.skill_name == skill_name)
    if session_id:
        query = query.where(Intent.session_id == session_id)
        count_query = count_query.where(Intent.session_id == session_id)
    if since:
        query = query.where(Intent.timestamp >= since)
        count_query = count_query.where(Intent.timestamp >= since)
    if until:
        query = query.where(Intent.timestamp <= until)
        count_query = count_query.where(Intent.timestamp <= until)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    result = await db.execute(query.offset(offset).limit(limit))
    items = [IntentResponse.model_validate(i) for i in result.scalars().all()]

    return IntentListResponse(items=items, total=total, limit=limit, offset=offset)
