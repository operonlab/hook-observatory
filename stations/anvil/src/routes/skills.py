"""Skill CRUD routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from db import Evaluation, Invocation, Skill, get_session
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class SkillCreateRequest(BaseModel):
    name: str
    version: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    io_schema: dict[str, Any] | None = None
    health_score: float | None = None
    status: str = "active"


class SkillUpdateRequest(BaseModel):
    version: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    io_schema: dict[str, Any] | None = None
    health_score: float | None = None
    status: str | None = None


class SkillResponse(BaseModel):
    id: str
    name: str
    version: str | None
    description: str | None
    tags: list[Any]
    io_schema: dict[str, Any] | None
    health_score: float | None
    status: str
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class SkillDetailResponse(SkillResponse):
    invocation_count: int = 0
    success_rate: float | None = None
    latest_eval_score: float | None = None


class SkillListResponse(BaseModel):
    items: list[SkillResponse]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/skills", status_code=201)
async def create_or_upsert_skill(
    body: SkillCreateRequest,
    db: AsyncSession = Depends(get_session),
) -> SkillResponse:
    """Register or upsert a skill."""
    values = body.model_dump(exclude_none=True)
    stmt = pg_insert(Skill).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["name"],
        set_={k: v for k, v in values.items() if k != "name"},
    )
    stmt = stmt.returning(Skill)
    result = await db.execute(stmt)
    await db.commit()
    row = result.fetchone()
    if row is None:
        raise HTTPException(status_code=500, detail="Upsert failed")
    skill = row[0] if hasattr(row[0], "id") else row
    # Re-fetch to get a proper ORM object
    refreshed = await db.execute(select(Skill).where(Skill.name == body.name))
    skill_obj = refreshed.scalar_one()
    return SkillResponse.model_validate(skill_obj)


@router.get("/skills")
async def list_skills(
    status: str | None = Query(None),
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> SkillListResponse:
    """List all skills with optional status filter and pagination."""
    query = select(Skill).order_by(Skill.name)
    count_query = select(func.count()).select_from(Skill)

    if status:
        query = query.where(Skill.status == status)
        count_query = count_query.where(Skill.status == status)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    result = await db.execute(query.offset(offset).limit(limit))
    items = [SkillResponse.model_validate(s) for s in result.scalars().all()]

    return SkillListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/skills/{name}")
async def get_skill(
    name: str,
    db: AsyncSession = Depends(get_session),
) -> SkillDetailResponse:
    """Get skill detail including latest stats and eval score."""
    result = await db.execute(select(Skill).where(Skill.name == name))
    skill = result.scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")

    # Invocation stats
    inv_count_result = await db.execute(
        select(func.count()).select_from(Invocation).where(Invocation.skill_name == name)
    )
    invocation_count = inv_count_result.scalar() or 0

    success_rate: float | None = None
    if invocation_count > 0:
        success_result = await db.execute(
            select(
                func.count().filter(Invocation.success.is_(True)).label("successes"),
            )
            .select_from(Invocation)
            .where(Invocation.skill_name == name)
        )
        successes = success_result.scalar() or 0
        success_rate = round(successes / invocation_count * 100, 2)

    # Latest eval score
    eval_result = await db.execute(
        select(Evaluation.benchmark_score)
        .where(Evaluation.skill_name == name)
        .order_by(Evaluation.run_timestamp.desc())
        .limit(1)
    )
    latest_eval_score = eval_result.scalar_one_or_none()

    base = SkillResponse.model_validate(skill).model_dump()
    return SkillDetailResponse(
        **base,
        invocation_count=invocation_count,
        success_rate=success_rate,
        latest_eval_score=latest_eval_score,
    )


@router.put("/skills/{name}")
async def update_skill(
    name: str,
    body: SkillUpdateRequest,
    db: AsyncSession = Depends(get_session),
) -> SkillResponse:
    """Update skill metadata."""
    result = await db.execute(select(Skill).where(Skill.name == name))
    skill = result.scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")

    update_data = body.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(skill, key, value)

    await db.commit()
    await db.refresh(skill)
    return SkillResponse.model_validate(skill)


@router.delete("/skills/{name}", status_code=200)
async def archive_skill(
    name: str,
    db: AsyncSession = Depends(get_session),
) -> SkillResponse:
    """Archive a skill (soft delete -- sets status to 'archived')."""
    result = await db.execute(select(Skill).where(Skill.name == name))
    skill = result.scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")

    skill.status = "archived"
    await db.commit()
    await db.refresh(skill)
    return SkillResponse.model_validate(skill)
