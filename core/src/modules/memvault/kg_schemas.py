"""Memvault KG Pydantic schemas — request/response types for Knowledge Graph."""

from datetime import datetime

from pydantic import AliasChoices, BaseModel, Field

from src.shared.schemas import SpaceScopedResponse

# ======================== Triple ========================


class TripleCreate(BaseModel):
    subject: str = Field(
        ...,
        max_length=500,
        validation_alias=AliasChoices("subject", "s"),
    )
    predicate: str = Field(
        ...,
        max_length=100,
        validation_alias=AliasChoices("predicate", "p"),
    )
    object: str = Field(
        validation_alias=AliasChoices("object", "o"),
    )
    source_session: str | None = Field(
        default=None,
        validation_alias=AliasChoices("source_session", "session_id"),
    )
    timestamp: datetime | None = None
    topic: str | None = Field(default=None, max_length=500)


class TripleBatchCreate(BaseModel):
    """Batch ingest from extract-triples pipeline."""

    session_id: str
    topic: str | None = None
    timestamp: datetime | None = None
    triples: list[TripleCreate]


class TripleResponse(SpaceScopedResponse):
    subject: str
    predicate: str
    object: str
    source_session: str | None = None
    timestamp: datetime | None = None
    topic: str | None = None
    display_zh: str | None = None
    # Edge invalidation
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    invalidated_by: str | None = None
    invalidation_reason: str | None = None
    # Entity resolution
    canonical_subject_id: str | None = None
    canonical_object_id: str | None = None
    # embedding intentionally excluded from response


# ======================== Community ========================


class CommunityResponse(SpaceScopedResponse):
    name: str
    resolution_level: int
    size: int
    top_entities: list[str] = []
    top_predicates: list[str] = []
    summary: str | None = None
    description_zh: str | None = None
    parent_community_id: str | None = None
    modularity_score: float | None = None
    generation_batch: str | None = None


class CommunityDetail(CommunityResponse):
    """Community with its member triples and children communities."""

    triples: list[TripleResponse] = []
    children: list["CommunityResponse"] = []


# ======================== CommunitySummary ========================


class CommunitySummaryResponse(SpaceScopedResponse):
    community_id: str
    summary: str
    key_findings: list[str] = []
    representative_triples: list[str] = []
    evidence_count: int | None = None
    tags: list[str] = []
    llm_model: str | None = None


# ======================== Attitude ========================


class AttitudeFactCreate(BaseModel):
    fact: str
    category: str = Field(..., max_length=100)
    source_sessions: list[str] = Field(default_factory=list)


class AttitudeFactUpdate(BaseModel):
    fact: str | None = None
    category: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class AttitudeFactResponse(SpaceScopedResponse):
    fact: str
    category: str
    operation: str
    confidence: float = 0.5
    source_sessions: list[str] = []
    superseded_by: str | None = None
    previous_version: str | None = None
    # embedding intentionally excluded from response


class AttitudeEvolveRequest(BaseModel):
    """Mem0 pattern: input a fact, system determines ADD/UPDATE/NOOP."""

    fact: str
    category: str = Field(..., max_length=100)
    source_session: str | None = None


class AttitudeEvolveResult(BaseModel):
    operation: str  # ADD/UPDATE/NOOP
    fact_id: str
    message: str
    previous_id: str | None = None  # for UPDATE


# ======================== Skill ========================


class SkillInvocationCreate(BaseModel):
    skill_name: str = Field(..., max_length=200)
    source_session: str = Field(..., max_length=64)
    cwd: str | None = Field(default=None, max_length=500)
    invoked_at: datetime
    outcome: str = Field(default="unknown")
    duration_ms: int | None = None


class SkillInvocationResponse(SpaceScopedResponse):
    skill_name: str
    source_session: str
    cwd: str | None = None
    invoked_at: datetime
    outcome: str = "unknown"
    duration_ms: int | None = None


class SkillProficiencyResponse(BaseModel):
    """Aggregated skill proficiency — computed from invocations, NOT a DB table."""

    skill_name: str
    invocation_count: int = 0
    success_count: int = 0
    success_rate: float = 0.0
    last_invoked: datetime | None = None
    proficiency: float = 0.0  # weighted score


# ======================== Pipeline Regenerate ========================


class CommunityRegenerateRequest(BaseModel):
    """Payload from community_pipeline.py — atomic community replacement."""

    communities: list[dict]
    generated_at: str | None = None
    resolution_level: int | None = None


class CommunitySummaryRegenerateRequest(BaseModel):
    """Payload from community_summary_pipeline.py — atomic summary replacement."""

    summaries: list[dict]
    generated_at: str | None = None


# ======================== Cascade Recall ========================


class CascadeRecallResult(BaseModel):
    """Multi-layer recall result."""

    summaries: list[CommunitySummaryResponse] = []  # L2
    communities: list[CommunityResponse] = []  # L1
    triples: list[TripleResponse] = []  # L0
    blocks: list = []  # existing blocks (import MemoryBlockResponse if needed)
    layers_searched: list[str] = []  # which layers returned results
    # Phase 2: Query routing metadata
    routing_intent: str | None = None
    routing_confidence: float | None = None
    # Phase 3: CRAG evaluation metadata
    confidence_score: float | None = None
    evaluation_verdict: str | None = None
    evaluation_metadata: dict | None = None


# ======================== Triple Invalidation ========================


class TripleInvalidateRequest(BaseModel):
    """Manual invalidation of a triple."""

    reason: str = Field(default="manual", max_length=50)
    replacement_triple_id: str | None = None


# ======================== Entity Resolution ========================


class EntityCanonicalResponse(SpaceScopedResponse):
    canonical_name: str
    aliases: list[str] = []
    entity_type: str = "concept"
    merge_count: int = 1


class EntityMergeRequest(BaseModel):
    primary_id: str
    secondary_id: str


class EntityMergeResult(BaseModel):
    merged_id: str
    canonical_name: str
    aliases: list[str]
    triples_updated: int


class EntityResolutionStats(BaseModel):
    total_entities: int
    total_aliases: int
    avg_merge_count: float
    unresolved_triples: int


# ======================== Graph Traversal ========================


class GraphNode(BaseModel):
    """A unique entity discovered during traversal."""

    id: str  # Entity name string
    label: str
    depth: int
    triple_count: int = 0


class GraphEdge(BaseModel):
    """A triple represented as a directed edge."""

    id: str  # Triple DB id
    source: str  # subject
    target: str  # object
    predicate: str
    depth: int


class GraphTraversalResult(BaseModel):
    """Graph structure for visualization."""

    seed_entity: str
    direction: str  # outgoing | incoming | both
    max_depth: int
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    total_triples_traversed: int = 0
    truncated: bool = False
