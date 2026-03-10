"""Taskflow Pydantic schemas — request/response types."""

from datetime import datetime

from pydantic import BaseModel, Field

from src.shared.schemas import SpaceScopedResponse, TimestampResponse

# ======================== Task ========================


class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    source: str  # personal / family / company
    project: str | None = None
    status: str = "todo"
    due_date: datetime | None = None
    start_date: datetime | None = None
    priority: str = "medium"  # urgent / high / medium / low
    estimated_hours: float | None = None
    recurrence: dict | None = None
    tags: list[str] | None = None
    parent_id: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    source: str | None = None
    project: str | None = None
    due_date: datetime | None = None
    start_date: datetime | None = None
    priority: str | None = None
    estimated_hours: float | None = None
    actual_hours: float | None = None
    recurrence: dict | None = None
    tags: list[str] | None = None
    parent_id: str | None = None


class TaskResponse(SpaceScopedResponse):
    title: str
    description: str | None = None
    source: str
    project: str | None = None
    status: str = "todo"
    due_date: datetime | None = None
    start_date: datetime | None = None
    completed_at: datetime | None = None
    priority: str = "medium"
    estimated_hours: float | None = None
    actual_hours: float | None = None
    recurrence: dict | None = None
    tags: list[str] | None = None
    parent_id: str | None = None
    deleted_at: datetime | None = None
    subtask_count: int = 0
    update_count: int = 0


# ======================== Task Update (progress report) ========================


class TaskUpdateCreate(BaseModel):
    type: str  # progress / blocker / note / status_change
    content: str
    hours_spent: float | None = None


class TaskUpdateResponse(TimestampResponse):
    id: str
    task_id: str
    type: str
    content: str
    old_status: str | None = None
    new_status: str | None = None
    hours_spent: float | None = None
    created_by: str | None = None


# ======================== Status Transition ========================


class StatusTransitionRequest(BaseModel):
    status: str  # target status
    comment: str | None = None


# ======================== Filters ========================


class TaskFilterParams(BaseModel):
    status: str | None = None
    source: str | None = None
    project: str | None = None
    priority: str | None = None
    tag: str | None = None
    search: str | None = None
    has_due_date: bool | None = None
    overdue: bool | None = None


# ======================== Search ========================


class TaskSearchResult(BaseModel):
    task: TaskResponse
    score: float


# ======================== Progress Stats ========================


class TaskProgressStats(BaseModel):
    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)
    by_priority: dict[str, int] = Field(default_factory=dict)
    overdue: int = 0
    total_estimated_hours: float = 0.0
    total_actual_hours: float = 0.0
