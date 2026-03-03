"""Memvault Pydantic schemas — request/response types."""

from datetime import datetime

from pydantic import BaseModel, Field

from src.shared.schemas import PaginatedResponse, SpaceScopedResponse  # noqa: F401

# --- Enums as string literals (lightweight, no enum import needed) ---

BLOCK_TYPES = {"knowledge", "skill", "attitude", "general"}

# Pipeline may produce finer-grained types — normalize to canonical KAS types
BLOCK_TYPE_ALIASES: dict[str, str] = {
    "insight": "knowledge",
    "achievement": "knowledge",
    "technical": "knowledge",
    "decision": "knowledge",
}


# ======================== MemoryBlock ========================


class MemoryBlockCreate(BaseModel):
    content: str
    block_type: str = Field(default="general")
    tags: list[str] = Field(default_factory=list)
    source_session: str | None = None


class MemoryBlockUpdate(BaseModel):
    content: str | None = None
    block_type: str | None = None
    tags: list[str] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class MemoryBlockResponse(SpaceScopedResponse):
    content: str
    block_type: str
    tags: list[str] = []
    source_session: str | None = None
    confidence: float = 0.0
    # embedding intentionally excluded from response (too large)


class MemoryBlockBrief(BaseModel):
    """Lightweight block representation for search results."""

    id: str
    content: str
    block_type: str
    tags: list[str] = []
    source_session: str | None = None
    confidence: float = 0.0
    score: float | None = None  # similarity score for search results
    created_at: datetime


# ======================== Tag ========================


class TagResponse(BaseModel):
    name: str
    usage_count: int


# ======================== KnowledgeDomain ========================


class KnowledgeDomainCreate(BaseModel):
    name: str = Field(..., max_length=200)
    description: str | None = None


class KnowledgeDomainUpdate(BaseModel):
    description: str | None = None
    maturity: float | None = Field(default=None, ge=0.0, le=1.0)


class KnowledgeDomainResponse(SpaceScopedResponse):
    name: str
    description: str | None = None
    maturity: float
    block_count: int


# ======================== ProfileScore ========================


class ProfileScoreResponse(SpaceScopedResponse):
    knowledge_score: float = 0.0
    attitude_score: float = 0.0
    skill_score: float = 0.0


class ProfileScoreUpdate(BaseModel):
    knowledge_score: float | None = Field(default=None, ge=0.0, le=100.0)
    attitude_score: float | None = Field(default=None, ge=0.0, le=100.0)
    skill_score: float | None = Field(default=None, ge=0.0, le=100.0)


# ======================== Search ========================


class SemanticSearchParams(BaseModel):
    q: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=100)


class SemanticSearchResult(BaseModel):
    block: MemoryBlockResponse
    score: float


class SearchMetadata(BaseModel):
    """Metadata about the search pipeline execution."""

    vector_used: bool = True
    keyword_used: bool = False
    scoring_applied: bool = True
    stages_applied: list[str] = []
    stages_skipped: list[str] = []
    reranker_used: bool = False
    adaptive_skipped: bool = False
    adaptive_reason: str | None = None
    noise_filtered: int = 0
    input_count: int = 0
    output_count: int = 0


class EnhancedSearchResult(BaseModel):
    results: list[SemanticSearchResult]
    metadata: SearchMetadata | None = None
