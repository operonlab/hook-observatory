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


# ── Cross-vault QA schemas (Phase 1b) ──


class AssistantQARequest(BaseModel):
    """Unified question → fan-out across memvault + docvault."""

    question: str = Field(..., min_length=1, max_length=4000)
    routing: str = Field(
        default="auto",
        pattern=r"^(auto|memory|doc|mixed)$",
        description="auto = LLM-classify; otherwise force a dispatch mode",
    )
    docvault_space: str | None = Field(
        default=None,
        description="Override docvault space_id; defaults to caller space (memvault always uses caller space)",
    )
    memvault_top_k: int = Field(default=5, ge=1, le=20)
    docvault_top_k: int = Field(default=20, ge=1, le=50)
    docvault_tags: list[str] | None = Field(
        default=None,
        description="Filter docvault chunks by tags (AND semantics)",
    )
    docvault_mode: str = Field(
        default="factual",
        pattern=r"^(factual|mixed)$",
        description="docvault QA pipeline mode (passed through to docvault)",
    )
    session_id: str | None = Field(default=None, max_length=64)


class CrossVaultCitation(BaseModel):
    """A single citation tagged with its source vault."""

    source: str = Field(..., pattern=r"^(memvault|docvault)$")
    score: float | None = None
    # memvault-side fields
    block_id: str | None = None
    block_content: str | None = None
    block_type: str | None = None
    # docvault-side fields
    document_id: str | None = None
    chunk_id: str | None = None
    section: str | None = None
    quote: str | None = None


class AssistantQAResponse(BaseModel):
    question: str
    answer: str
    routing_decision: str = Field(..., pattern=r"^(memory|doc|mixed)$")
    routing_model: str = ""
    routing_fallback: bool = False
    memvault_hits: int = 0
    docvault_hits: int = 0
    citations: list[CrossVaultCitation] = []
    docvault_qa_log_id: str | None = None
