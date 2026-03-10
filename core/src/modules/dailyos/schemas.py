"""Daily OS Pydantic schemas — request/response types."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.shared.schemas import SpaceScopedResponse

# ======================== Method ========================


class MethodCreate(BaseModel):
    slug: str
    name: str
    name_zh: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    config: dict = Field(default_factory=dict)
    layout_type: str = "list"
    tags: list[str] | None = None


class MethodUpdate(BaseModel):
    slug: str | None = None
    name: str | None = None
    name_zh: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    config: dict | None = None
    layout_type: str | None = None
    tags: list[str] | None = None


class MethodResponse(SpaceScopedResponse):
    slug: str
    name: str
    name_zh: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    is_preset: bool = False
    cloned_from_id: str | None = None
    config: dict = Field(default_factory=dict)
    version: int = 1
    layout_type: str = "list"
    tags: list[str] | None = None
    deleted_at: datetime | None = None


# ======================== Method Selection ========================


class MethodSelectionCreate(BaseModel):
    method_id: str
    context: str = "default"
    overrides: dict | None = None


class MethodSelectionUpdate(BaseModel):
    overrides: dict | None = None


class MethodSelectionResponse(SpaceScopedResponse):
    method_id: str
    context: str = "default"
    is_active: bool = True
    overrides: dict | None = None
    activated_at: datetime
    deactivated_at: datetime | None = None
    method: MethodResponse | None = None
    deleted_at: datetime | None = None


class MethodActivateRequest(BaseModel):
    method_id: str
    context: str = "default"
    overrides: dict | None = None


class DimensionConflict(BaseModel):
    dimension: str
    replaced_method_id: str
    replaced_method_name: str


class MethodActivateResponse(BaseModel):
    selection: MethodSelectionResponse
    replaced: list[DimensionConflict] = Field(default_factory=list)
    active_count: int = 1


# ======================== Daily Plan ========================


class DailyPlanCreate(BaseModel):
    plan_date: date
    context: str = "default"


class DailyPlanUpdate(BaseModel):
    items: list[dict] | None = None
    method_state: dict | None = None
    reflection: str | None = None
    completion_score: float | None = None


class DailyPlanResponse(SpaceScopedResponse):
    plan_date: date
    context: str = "default"
    method_selection_id: str | None = None
    status: str = "planning"
    items: list[dict] = Field(default_factory=list)
    method_state: dict | None = None
    reflection: str | None = None
    completion_score: float | None = None
    deleted_at: datetime | None = None


# ======================== Strategy Preview ========================


class PlanTransitionRequest(BaseModel):
    status: str
    comment: str | None = None


class MethodPreviewResponse(BaseModel):
    method: MethodResponse
    suggested_items: list[dict] = Field(default_factory=list)
    frog_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ======================== Search ========================


class DailyOSSearchResult(BaseModel):
    entity_type: str  # "plan" or "method"
    entity_id: str
    score: float
    content_preview: str
    metadata: dict = Field(default_factory=dict)


# ======================== Recurring Items ========================


class RecurringItemCreate(BaseModel):
    title: str
    recurrence_type: Literal["daily", "weekly", "monthly"]
    day_of_week: int | None = None
    day_of_month: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    category: str | None = None


class RecurringItemUpdate(BaseModel):
    title: str | None = None
    recurrence_type: Literal["daily", "weekly", "monthly"] | None = None
    day_of_week: int | None = None
    day_of_month: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    category: str | None = None
    is_active: bool | None = None


class RecurringItemResponse(BaseModel):
    id: str
    title: str
    recurrence_type: str
    day_of_week: int | None = None
    day_of_month: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    category: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
