"""Shared SSE (Server-Sent Events) utilities for streaming responses."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class BlockType(StrEnum):
    THINKING = "thinking"
    CONTENT = "content"
    SOURCE = "source"
    PROGRESS = "progress"
    ERROR = "error"
    DONE = "done"


class StreamBlock(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    type: BlockType
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


def format_sse(block: StreamBlock) -> dict:
    """Format a StreamBlock as SSE event dict for sse-starlette."""
    return {
        "event": block.type.value,
        "id": block.id,
        "data": block.model_dump_json(),
    }
