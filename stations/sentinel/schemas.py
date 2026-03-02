"""Pydantic request/response schemas for Sentinel API."""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── Health Check ──


class ServiceStatus(BaseModel):
    service: str
    status: str  # operational / degraded / partial_outage / major_outage / maintenance
    light_status: str | None = None
    deep_status: str | None = None
    last_check: str | None = None
    response_ms: float | None = None
    uptime_90d: float | None = None


class OverallStatus(BaseModel):
    status: str  # all_operational / partial_outage / major_outage / maintenance
    services: list[ServiceStatus]
    checked_at: str


# ── Notify / Resolve ──


class NotifyRequest(BaseModel):
    service: str
    action: str
    agent_id: str
    pid: int | None = None
    estimated_duration: int = Field(default=300, ge=10, le=7200)


class NotifyResponse(BaseModel):
    id: str
    message: str


class ResolveRequest(BaseModel):
    service: str
    agent_id: str
    result: str = "success"  # success / failure


class ResolveResponse(BaseModel):
    message: str
    operation_id: str | None = None


# ── Incidents ──


class IncidentResponse(BaseModel):
    id: str
    service: str
    status: str
    severity: str
    title: str
    detail: str | None = None
    created_at: str
    resolved_at: str | None = None


class IncidentListResponse(BaseModel):
    items: list[IncidentResponse]
    total: int
    page: int
    page_size: int


# ── Uptime ──


class DayUptime(BaseModel):
    date: str
    uptime_pct: float
    status: str  # operational / degraded / outage / maintenance / no_data


class ServiceUptime(BaseModel):
    service: str
    days: list[DayUptime]


class UptimeResponse(BaseModel):
    services: list[ServiceUptime]


# ── Subscription ──


class SubscribeRequest(BaseModel):
    url: str
    events: list[str] = Field(default=["*"])


class SubscribeResponse(BaseModel):
    id: str
    message: str


# ── Generic ──


class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"


class ActiveOperationResponse(BaseModel):
    id: str
    service: str
    action: str
    agent_id: str
    pid: int | None = None
    estimated_duration: int
    created_at: str
    resolved_at: str | None = None
    result: str | None = None
