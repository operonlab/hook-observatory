"""Nodeflow Pydantic schemas — request/response types."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.shared.schemas import SpaceScopedResponse

# ======================== Flow ========================


class FlowCreate(BaseModel):
    name: str
    description: str | None = None
    trigger_type: str = "event"
    trigger_config: dict[str, Any] | None = None
    status: str = "draft"


class FlowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger_type: str | None = None
    trigger_config: dict[str, Any] | None = None
    status: str | None = None


class FlowResponse(SpaceScopedResponse):
    name: str
    description: str | None = None
    trigger_type: str
    trigger_config: dict[str, Any] | None = None
    status: str
    deleted_at: datetime | None = None


# ======================== Node ========================


class NodeCreate(BaseModel):
    flow_id: str
    node_type: str
    label: str
    config: dict[str, Any] | None = None
    position_x: float = 0
    position_y: float = 0


class NodeUpdate(BaseModel):
    node_type: str | None = None
    label: str | None = None
    config: dict[str, Any] | None = None
    position_x: float | None = None
    position_y: float | None = None


class NodeResponse(SpaceScopedResponse):
    flow_id: str
    node_type: str
    label: str
    config: dict[str, Any] | None = None
    position_x: float
    position_y: float
    deleted_at: datetime | None = None


# ======================== Edge ========================


class EdgeCreate(BaseModel):
    flow_id: str
    source_node_id: str
    target_node_id: str
    source_port: str = "output"


class EdgeResponse(SpaceScopedResponse):
    flow_id: str
    source_node_id: str
    target_node_id: str
    source_port: str
    deleted_at: datetime | None = None


# ======================== Flow Run ========================


class FlowRunResponse(SpaceScopedResponse):
    flow_id: str
    status: str
    trigger_event: dict[str, Any] | None = None
    started_at: datetime
    finished_at: datetime | None = None
    error: str | None = None
    deleted_at: datetime | None = None


# ======================== Node Run Log ========================


class NodeRunLogResponse(SpaceScopedResponse):
    flow_run_id: str
    node_id: str
    status: str
    input_data: dict[str, Any] | None = None
    output_data: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    deleted_at: datetime | None = None


# ======================== Detail (Nested) ========================


class FlowDetailResponse(FlowResponse):
    """Flow with its nodes and edges included."""

    nodes: list[NodeResponse] = Field(default_factory=list)
    edges: list[EdgeResponse] = Field(default_factory=list)


class FlowRunDetailResponse(FlowRunResponse):
    """Flow run with its node run logs included."""

    node_run_logs: list[NodeRunLogResponse] = Field(default_factory=list)
