"""Correction management routes."""

from __future__ import annotations

from datetime import datetime

from db import Correction, get_session
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CorrectionCreateRequest(BaseModel):
    skill_name: str
    level: int = 0
    trigger_reason: str
    before_score: float | None = None
    after_score: float | None = None
    diff_content: str | None = None


class CorrectionUpdateRequest(BaseModel):
    status: str  # approved, executed, reverted
    approved_by: str | None = None
    after_score: float | None = None


class CorrectionResponse(BaseModel):
    id: str
    skill_name: str
    level: int
    trigger_reason: str
    before_score: float | None
    after_score: float | None
    diff_content: str | None
    approved_by: str | None
    approved_at: datetime | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CorrectionListResponse(BaseModel):
    items: list[CorrectionResponse]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/corrections", status_code=201)
async def propose_correction(
    body: CorrectionCreateRequest,
    db: AsyncSession = Depends(get_session),
) -> CorrectionResponse:
    """Propose a new correction."""
    correction = Correction(**body.model_dump())
    db.add(correction)
    await db.commit()
    await db.refresh(correction)
    return CorrectionResponse.model_validate(correction)


@router.get("/corrections")
async def list_corrections(
    skill_name: str | None = Query(None),
    status: str | None = Query(None),
    level: int | None = Query(None),
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> CorrectionListResponse:
    """List corrections with filters."""
    query = select(Correction).order_by(Correction.created_at.desc())
    count_query = select(func.count()).select_from(Correction)

    if skill_name:
        query = query.where(Correction.skill_name == skill_name)
        count_query = count_query.where(Correction.skill_name == skill_name)
    if status:
        query = query.where(Correction.status == status)
        count_query = count_query.where(Correction.status == status)
    if level is not None:
        query = query.where(Correction.level == level)
        count_query = count_query.where(Correction.level == level)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    result = await db.execute(query.offset(offset).limit(limit))
    items = [CorrectionResponse.model_validate(c) for c in result.scalars().all()]

    return CorrectionListResponse(items=items, total=total, limit=limit, offset=offset)


@router.put("/corrections/{correction_id}")
async def update_correction(
    correction_id: str,
    body: CorrectionUpdateRequest,
    db: AsyncSession = Depends(get_session),
) -> CorrectionResponse:
    """Update correction status (approve, execute, revert)."""
    result = await db.execute(select(Correction).where(Correction.id == correction_id))
    correction = result.scalar_one_or_none()
    if correction is None:
        raise HTTPException(status_code=404, detail=f"Correction '{correction_id}' not found")

    correction.status = body.status
    if body.approved_by:
        correction.approved_by = body.approved_by
    if body.after_score is not None:
        correction.after_score = body.after_score

    # Set approved_at when status transitions to approved
    if body.status == "approved" and correction.approved_at is None:
        correction.approved_at = func.now()

    await db.commit()
    await db.refresh(correction)
    return CorrectionResponse.model_validate(correction)
