"""Pydantic schemas for browser-bridge."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    active = "active"
    closed = "closed"
    error = "error"


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"


# --- Request schemas ---

class ChatRequest(BaseModel):
    provider: str = Field(..., description="Provider name, e.g. 'grok', 'notebooklm'")
    prompt: str = Field(..., description="User prompt to send")
    timeout: int = Field(120, description="Max seconds to wait for response")
    conversation_id: str | None = Field(None, description="Continue existing conversation")


class NewConversationRequest(BaseModel):
    provider: str


# --- Response schemas ---

class BridgeResponse(BaseModel):
    status: str = "ok"
    provider: str
    response: str = ""
    artifacts: list[str] = Field(default_factory=list, description="URLs or file paths")
    elapsed: float = 0.0
    session_id: str = ""
    conversation_id: str = ""
    message_id: int | None = None
    error: str | None = None


class SessionInfo(BaseModel):
    id: str
    provider: str
    status: SessionStatus
    created_at: datetime
    last_active: datetime | None = None


class ConversationInfo(BaseModel):
    id: str
    session_id: str
    title: str | None = None
    created_at: datetime
    message_count: int = 0


class MessageInfo(BaseModel):
    id: int
    conversation_id: str
    role: MessageRole
    content: str
    artifacts: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    version: str
    providers: list[str] = Field(default_factory=list)
    active_sessions: int = 0


class ProviderInfo(BaseModel):
    name: str
    base_url: str
    description: str = ""
    supports_conversation: bool = True


# --- Config ---

class BridgeConfig(BaseModel):
    port: int = 4106
    db_path: str = "data/bridge.db"
    poll_interval: float = 2.0
    poll_threshold: int = 3
    default_timeout: int = 120
    pw_master_profile: str = "~/.playwright-profiles/master"
