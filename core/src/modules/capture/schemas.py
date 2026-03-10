"""Capture schemas — request/response models."""

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

# Modules that support capture (whitelist)
CAPTURABLE_MODULES = {"finance", "invest", "taskflow", "ideagraph", "intelflow", "dailyos"}

MAX_PAYLOAD_BYTES = 16 * 1024  # 16KB
BATCH_LIMIT = 50


class CaptureCreate(BaseModel):
    module: str = Field(max_length=64)
    entity_type: str = Field(max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    raw_input: str | None = None
    group_id: str | None = None


class CaptureUpdate(BaseModel):
    payload: dict[str, Any] | None = None
    raw_input: str | None = None

    @field_validator("payload")
    @classmethod
    def validate_payload_size(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and len(json.dumps(v)) > MAX_PAYLOAD_BYTES:
            raise ValueError(f"Payload exceeds {MAX_PAYLOAD_BYTES} byte limit")
        return v


class CaptureResponse(BaseModel):
    id: str
    space_id: str
    module: str
    entity_type: str
    payload: dict[str, Any]
    raw_input: str | None
    completeness: float
    status: str
    version: int = 1
    group_id: str | None = None
    promoted_id: str | None = None
    promoted_at: datetime | None = None
    expires_at: datetime | None = None
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


class BatchFillRequest(BaseModel):
    capture_ids: list[str] = Field(max_length=BATCH_LIMIT)
    payload: dict[str, Any]

    @field_validator("payload")
    @classmethod
    def validate_payload_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v)) > MAX_PAYLOAD_BYTES:
            raise ValueError(f"Payload exceeds {MAX_PAYLOAD_BYTES} byte limit")
        return v


class CaptureSearchResult(BaseModel):
    capture: CaptureResponse
    score: float


class CaptureEnrichmentResponse(BaseModel):
    id: str
    capture_id: str
    agent_id: str | None
    delta: dict[str, Any]
    previous_values: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}
