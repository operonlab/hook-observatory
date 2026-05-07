"""Request/response schemas for the assistant module."""

from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    mode: str = Field(..., pattern=r"^(workshop|blog)$")
    module: str | None = Field(None, description="Current module name (workshop mode)")
    session_id: str | None = Field(None, description="Frontend-generated session ID (12 hex chars)")
    conversation_id: str | None = Field(None, description="Conversation ID for continuity")


class ChatMessage(BaseModel):
    role: str
    content: str


# ── QA Log schemas ──


class QaLogResponse(BaseModel):
    id: str
    session_id: str | None
    question: str
    answer: str
    tokens_in: int | None
    tokens_out: int | None
    duration_ms: int | None
    flagged: bool
    flag_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FlagRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)
