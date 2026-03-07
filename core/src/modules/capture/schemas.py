"""Capture schemas — request/response models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CaptureCreate(BaseModel):
    module: str  # 'finance', 'invest', 'taskflow'
    entity_type: str  # 'transaction', 'subscription', 'trade', 'task'
    payload: dict[str, Any] = Field(default_factory=dict)
    raw_input: str | None = None


class CaptureUpdate(BaseModel):
    payload: dict[str, Any] | None = None
    raw_input: str | None = None


class CaptureResponse(BaseModel):
    id: str
    space_id: str
    module: str
    entity_type: str
    payload: dict[str, Any]
    raw_input: str | None
    completeness: float
    status: str
    promoted_id: str | None
    promoted_at: datetime | None
    expires_at: datetime | None
    missing_fields: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CapturePromoteResult(BaseModel):
    success: bool
    capture_id: str
    promoted_id: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    error: str | None = None


class CaptureStats(BaseModel):
    total: int
    by_module: dict[str, int]
    by_status: dict[str, int]
