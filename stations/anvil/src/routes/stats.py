"""Aggregated statistics routes."""

from __future__ import annotations

from db import get_session
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from services.telemetry import TelemetryService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class TopSkillStat(BaseModel):
    skill_name: str
    count: int
    success_rate: float


class TrendBucket(BaseModel):
    day: str
    count: int


class GlobalStatsResponse(BaseModel):
    total_invocations: int
    total_skills: int
    avg_success_rate: float
    top_skills: list[TopSkillStat]
    trend_7d: list[TrendBucket]


class DailyCount(BaseModel):
    day: str
    count: int


class CommonError(BaseModel):
    error_message: str
    count: int


class SkillStatsResponse(BaseModel):
    skill_name: str
    total_invocations: int
    avg_duration_ms: float | None
    failure_rate: float
    daily_counts: list[DailyCount]
    common_errors: list[CommonError]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/stats")
async def global_stats(
    db: AsyncSession = Depends(get_session),
) -> GlobalStatsResponse:
    """Aggregated stats: top skills by count, avg success rate, 7d trend."""
    svc = TelemetryService(db)
    data = await svc.get_global_stats()
    return GlobalStatsResponse(**data)


@router.get("/stats/{name}")
async def skill_stats(
    name: str,
    db: AsyncSession = Depends(get_session),
) -> SkillStatsResponse:
    """Per-skill stats: daily counts, avg duration, failure rate, common errors."""
    svc = TelemetryService(db)
    data = await svc.get_skill_stats(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"No invocations found for skill '{name}'")
    return SkillStatsResponse(**data)
