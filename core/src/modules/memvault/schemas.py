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
    "skill_knowledge": "knowledge",
    "pattern": "knowledge",
    "preference": "attitude",
}


# ======================== MemoryBlock ========================


class MemoryBlockCreate(BaseModel):
    content: str
    block_type: str = Field(default="general")
    tags: list[str] = Field(default_factory=list)
    source_session: str | None = Field(default=None)


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
    invalid_at: datetime | None = None
    superseded_by: str | None = None
    invalidation_reason: str | None = None


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


class ProfileScoreUpdate(BaseModel):
    knowledge_score: float | None = Field(default=None, ge=0.0, le=100.0)
    attitude_score: float | None = Field(default=None, ge=0.0, le=100.0)


# ======================== Search ========================


class SemanticSearchParams(BaseModel):
    q: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=100)
    date_from: datetime | None = Field(default=None, description="Filter: created_at >= date_from")
    date_to: datetime | None = Field(default=None, description="Filter: created_at <= date_to")


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
    reranker_gated: bool = False
    reranker_gate_reason: str | None = None
    adaptive_skipped: bool = False
    adaptive_reason: str | None = None
    noise_filtered: int = 0
    injection_sanitized: int = 0  # G2: count of results sanitized for injection safety
    input_count: int = 0
    output_count: int = 0
    scope: str | None = None
    backend: str | None = None
    routing_tags: list[str] | None = None  # NEW: inferred domain tags used for pre-filtering


class EnhancedSearchResult(BaseModel):
    results: list[SemanticSearchResult]
    metadata: SearchMetadata | None = None


# ======================== Fast / Slow Memory Query ========================


class MemoryQueryRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=2000)
    task_mode: str = Field(default="auto", description="auto | lookup | decide | build | reflect")
    thinking_mode: str = Field(default="auto", description="auto | fast | slow")
    load_budget: str = Field(default="standard", description="light | standard | deep")
    consumer: str = Field(default="human", description="agent | human | ui")
    top_k: int = Field(default=6, ge=1, le=20)


class MemoryEvidenceRef(BaseModel):
    kind: str
    ref_id: str
    title: str
    snippet: str | None = None
    score: float | None = None


class MemoryCard(BaseModel):
    id: str
    title: str
    summary: str
    why_relevant: str
    use_now: str
    layer: str
    source_type: str
    confidence: float = 0.0
    freshness: str | None = None
    tags: list[str] = []
    evidence_refs: list[MemoryEvidenceRef] = []
    source: str | None = None  # None=normal, "speculative_prefetch"=predicted hit


class MemoryQueryStrategy(BaseModel):
    task_mode: str
    thinking_mode_requested: str
    thinking_mode_used: str
    load_budget: str
    consumer: str


class MemoryQueryResponse(BaseModel):
    query: str
    strategy: MemoryQueryStrategy
    fast_cards: list[MemoryCard] = []
    working_cards: list[MemoryCard] = []
    deep_cards: list[MemoryCard] = []
    highlights: list[str] = []
    metadata: dict | None = None


class MemoryInjectResponse(BaseModel):
    query: str
    strategy: MemoryQueryStrategy
    system_prompt_memory: str
    working_context: list[str] = []
    decision_bias: list[str] = []
    cards: list[MemoryCard] = []
    metadata: dict | None = None


class MemoryInspectResponse(BaseModel):
    query: str
    strategy: MemoryQueryStrategy
    cards: list[MemoryCard] = []
    raw_sections: dict[str, list[MemoryEvidenceRef]] = {}
    metadata: dict | None = None


# ======================== Reflection / Curate ========================


class ReflectionResponse(BaseModel):
    session_id: str
    block_count: int
    invariants: list[str]
    derived: list[str]
    corrections: list[str]
    triples_created: int
    triples_invalidated: int
    reflected_at: str


class CurateRequest(BaseModel):
    confidence_threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    dry_run: bool = False


class CurateResponse(BaseModel):
    blocks_soft_deleted: int
    triples_invalidated: int
    orphan_triples_cleaned: int
    dry_run: bool


# ======================== Search Feedback ========================


class SessionSummary(BaseModel):
    """Aggregated session view — one row per source_session."""

    source_session: str
    block_count: int
    first_at: datetime
    last_at: datetime
    block_types: list[str] = []


# ======================== Search Feedback ========================


class SearchFeedbackCreate(BaseModel):
    entity_id: str = Field(..., description="Block ID that was rated")
    query: str = Field(..., min_length=1, max_length=2000, description="Original search query")
    signal: str = Field(..., pattern="^(positive|negative)$", description="positive or negative")
    feedback_source: str = Field(default="agent", pattern="^(agent|user|implicit)$")


class SearchFeedbackResponse(BaseModel):
    id: str
    entity_id: str
    query_hash: str
    signal: str
    feedback_source: str
    created_at: datetime


class FeedbackAggregateResponse(BaseModel):
    entity_id: str
    positive_count: int
    negative_count: int
    net_signal: int
