"""Request/response schemas for the assistant module."""

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
