"""Daily OS P1 Pydantic schemas — Micro-Strategy Toggles, Task Funnel, Capacity Bar."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.shared.schemas import SpaceScopedResponse

# ======================== P1a: User Toggles ========================


class ToggleUpsert(BaseModel):
    enabled: bool
    category: str | None = None
    config: dict | None = None
    source: str = "manual"


class BatchToggleItem(BaseModel):
    toggle_key: str
    enabled: bool
    category: str | None = None
    config: dict | None = None


class BatchToggleRequest(BaseModel):
    toggles: list[BatchToggleItem]
    source: str = "manual"


class ApplyWorkflowTogglesRequest(BaseModel):
    workflow_id: str
    toggle_overrides: dict[str, bool] = Field(default_factory=dict)


class ToggleResponse(SpaceScopedResponse):
    toggle_key: str
    enabled: bool
    category: str | None = None
    config: dict | None = None
    source: str = "manual"
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ToggleCategoryResponse(BaseModel):
    category: str
    count: int


# ======================== P1b: Task Funnel (Backlog) ========================

FunnelLayer = Literal["backburner", "master", "ready", "scheduled"]
Priority = Literal["low", "medium", "high", "critical"]


class BacklogItemCreate(BaseModel):
    title: str
    funnel_layer: FunnelLayer = "master"
    priority: Priority = "medium"
    labels: list[str] | None = None
    energy_level: int | None = Field(None, ge=1, le=5)
    duration_min: int | None = Field(None, ge=1)
    cognitive_cost: int | None = Field(None, ge=1, le=5)
    do_date: date | None = None
    due_date: date | None = None
    start_date: date | None = None
    parent_id: str | None = None
    notes: str | None = None
    source_module: str | None = None
    source_id: str | None = None
    reward_points: int = 1
    is_frog: bool = False
    extra: dict | None = None


class BacklogItemUpdate(BaseModel):
    title: str | None = None
    funnel_layer: FunnelLayer | None = None
    priority: Priority | None = None
    labels: list[str] | None = None
    energy_level: int | None = Field(None, ge=1, le=5)
    duration_min: int | None = Field(None, ge=1)
    cognitive_cost: int | None = Field(None, ge=1, le=5)
    do_date: date | None = None
    due_date: date | None = None
    start_date: date | None = None
    parent_id: str | None = None
    notes: str | None = None
    reward_points: int | None = None
    is_frog: bool | None = None
    extra: dict | None = None


class BacklogItemResponse(SpaceScopedResponse):
    title: str
    funnel_layer: str
    priority: str
    labels: list[str] | None = None
    energy_level: int | None = None
    duration_min: int | None = None
    cognitive_cost: int | None = None
    do_date: date | None = None
    due_date: date | None = None
    start_date: date | None = None
    parent_id: str | None = None
    notes: str | None = None
    source_module: str | None = None
    source_id: str | None = None
    reward_points: int = 1
    is_frog: bool = False
    defer_count: int = 0
    extra: dict | None = None
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class FunnelLayerGroup(BaseModel):
    layer: str
    items: list[BacklogItemResponse]
    count: int


class FunnelGroupedResponse(BaseModel):
    backburner: list[BacklogItemResponse] = Field(default_factory=list)
    master: list[BacklogItemResponse] = Field(default_factory=list)
    ready: list[BacklogItemResponse] = Field(default_factory=list)
    scheduled: list[BacklogItemResponse] = Field(default_factory=list)
    total: int = 0


class FunnelStats(BaseModel):
    backburner: int = 0
    master: int = 0
    ready: int = 0
    scheduled: int = 0
    total: int = 0


# ======================== P1c: Capacity History ========================

BudgetType = Literal["time", "cognitive"]


class CapacityLogRequest(BaseModel):
    log_date: date
    budget_type: BudgetType = "time"
    planned_value: float = Field(0.0, ge=0)
    actual_value: float = Field(0.0, ge=0)
    unit: str = "minutes"
    energy_start: int | None = Field(None, ge=1, le=5)
    energy_end: int | None = Field(None, ge=1, le=5)
    mood: int | None = Field(None, ge=1, le=5)
    notes: str | None = None


class CapacityHistoryResponse(SpaceScopedResponse):
    log_date: date
    budget_type: str
    planned_value: float
    actual_value: float
    unit: str
    energy_start: int | None = None
    energy_end: int | None = None
    mood: int | None = None
    notes: str | None = None
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CapacityBaselineResponse(BaseModel):
    budget_type: str
    planned_mean: float
    planned_std: float
    actual_mean: float
    actual_std: float
    sample_days: int
    unit: str
