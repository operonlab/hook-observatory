"""Assistant module routes — SSE streaming chat endpoint + QA log management."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from src.shared.deps import get_db, require_permission
from src.shared.sse import format_sse

from .context_builder import build_context
from .cross_vault_service import cross_vault_qa
from .schemas import (
    AssistantQARequest,
    AssistantQAResponse,
    ChatRequest,
    FlagRequest,
    QaLogResponse,
)
from .services import flag_qa_log, list_qa_logs, stream_chat

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("assistant.write"),
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


@router.post("/qa", response_model=AssistantQAResponse)
async def cross_vault_qa_endpoint(
    body: AssistantQARequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("assistant.write"),
):
    """Unified cross-vault QA — LLM classifies intent, then fans out to
    memvault.recall and/or docvault.qa. Returns synthesized answer +
    citations tagged with source vault."""
    space_id = user.get("space_id", "default")
    created_by = user.get("user_id")
    return await cross_vault_qa(
        db=db,
        request=body,
        space_id=space_id,
        created_by=created_by,
    )


@router.get("/qa-logs", response_model=list[QaLogResponse])
async def get_qa_logs(
    limit: int = 50,
    flagged: bool | None = None,
    session_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("admin.read"),
):
    """List recent QA log records (admin view). Filterable by flagged status and session_id."""
    records = await list_qa_logs(db, limit=limit, flagged=flagged, session_id=session_id)
    return [QaLogResponse.model_validate(r) for r in records]


@router.post("/qa-logs/{log_id}/flag", response_model=QaLogResponse)
async def flag_log(
    log_id: str,
    body: FlagRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("admin.write"),
):
    """Flag a QA log record as a bad answer."""
    record = await flag_qa_log(db, log_id, reason=body.reason)
    return QaLogResponse.model_validate(record)


@router.get("/status")
async def status():
    """Health check for sentinel."""
    return {"status": "ok", "module": "assistant"}
