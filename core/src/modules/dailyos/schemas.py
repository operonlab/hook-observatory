"""Daily OS Pydantic schemas — request/response types."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


# ======================== Plan Stats ========================


class DailyPlanStats(BaseModel):
    plan_date: date
    status: str
    total_items: int
    done_count: int
    completion_score: float


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


# ======================== Task Groups ========================


class TaskGroupCreate(BaseModel):
    name: str
    color: str = "#cba6f7"
    icon: str | None = None
    sort_order: int = 0


class TaskGroupUpdate(BaseModel):
    name: str | None = None
    color: str | None = None
    icon: str | None = None
    sort_order: int | None = None


class TaskGroupResponse(BaseModel):
    id: str
    name: str
    color: str
    icon: str | None = None
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ======================== Recurring Items ========================


class RecurringItemCreate(BaseModel):
    title: str
    recurrence_type: Literal["daily", "weekly", "monthly"]
    day_of_week: int | None = None
    day_of_month: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    category: str | None = None
    group_id: str | None = None

    @model_validator(mode="after")
    def validate_recurrence_fields(self):
        if self.recurrence_type == "weekly" and self.day_of_week is None:
            raise ValueError("day_of_week is required for weekly recurrence")
        if self.recurrence_type == "monthly" and self.day_of_month is None:
            raise ValueError("day_of_month is required for monthly recurrence")
        return self


class RecurringItemUpdate(BaseModel):
    title: str | None = None
    recurrence_type: Literal["daily", "weekly", "monthly"] | None = None
    day_of_week: int | None = None
    day_of_month: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    category: str | None = None
    group_id: str | None = None
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
    group_id: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ======================== Activity Spans ========================


class ActivitySpanCreate(BaseModel):
    title: str
    start_date: date
    end_date: date
    category: str | None = None
    color: str = "#89b4fa"
    notes: str | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self


class ActivitySpanUpdate(BaseModel):
    title: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    category: str | None = None
    color: str | None = None
    notes: str | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date is not None and self.end_date is not None:
            if self.end_date < self.start_date:
                raise ValueError("end_date must be >= start_date")
        return self


class ActivitySpanResponse(BaseModel):
    id: str
    title: str
    start_date: date
    end_date: date
    category: str | None = None
    color: str
    notes: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
