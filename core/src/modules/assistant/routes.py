"""Assistant module routes — SSE streaming chat endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from src.shared.deps import get_db, require_permission
from src.shared.sse import format_sse

from .context_builder import build_context
from .schemas import ChatRequest
from .services import stream_chat

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("assistant.read"),
):
    """Stream AI chat response with context-aware RAG.

    Supports two modes:
    - workshop: cross-module context from memvault + module hints
    - blog: blog article search via memvault (tag: blog)
    """
    space_id = user.get("space_id", "default")

    # Build context messages
    context_messages = await build_context(
        mode=body.mode,
        message=body.message,
        module=body.module,
        space_id=space_id,
        db=db,
    )

    # Append user message
    messages = context_messages + [{"role": "user", "content": body.message}]

    async def event_generator():
        async for block in stream_chat(messages, session_id=body.session_id):
            yield format_sse(block)

    return EventSourceResponse(event_generator())


@router.get("/status")
async def status():
    """Health check for sentinel."""
    return {"status": "ok", "module": "assistant"}
