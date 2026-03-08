"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# --- Request ---


class EventIngest(BaseModel):
    event_type: str = Field(default="unknown", alias="hook_event_name")
    session_id: str | None = None
    cwd: str | None = None
    tool_name: str | None = None
    hook_name: str | None = None
    payload: dict = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


# --- Response ---


class HealthResponse(BaseModel):
    status: str = "ok"
    spool_dir: str = ""
    total_events_processed: int = 0
    pending_files: int = 0


class EventResponse(BaseModel):
    id: str
    event_type: str
    session_id: str | None
    cwd: str | None
    tool_name: str | None
    hook_name: str | None
    payload: dict
    created_at: datetime


class EventListResponse(BaseModel):
    items: list[EventResponse]
    total: int
    limit: int
    offset: int


class SummaryStats(BaseModel):
    total: int
    today: int
    unique_sessions: int


class EventTypeStats(BaseModel):
    event_type: str
    count: int
    today: int


class ToolStats(BaseModel):
    tool_name: str
    count: int


class SessionStats(BaseModel):
    session_id: str
    event_count: int
    first_seen: datetime
    last_seen: datetime


class TimelineBucket(BaseModel):
    bucket: datetime
    count: int


class AllStats(BaseModel):
    summary: SummaryStats
    by_event: list[EventTypeStats]
    by_tool: list[ToolStats]
    sessions: list[SessionStats]
    timeline: list[TimelineBucket]
