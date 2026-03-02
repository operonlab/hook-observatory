"""Memvault KG Pydantic schemas — request/response types for Knowledge Graph."""

from datetime import datetime

from pydantic import AliasChoices, BaseModel, Field

from src.shared.schemas import SpaceScopedResponse

# ======================== Triple ========================


class TripleCreate(BaseModel):
    subject: str = Field(
        ..., max_length=500, validation_alias=AliasChoices("subject", "s"),
    )
    predicate: str = Field(
        ..., max_length=100, validation_alias=AliasChoices("predicate", "p"),
    )
    object: str = Field(
        validation_alias=AliasChoices("object", "o"),
    )
    source_session: str | None = Field(
        default=None, validation_alias=AliasChoices("source_session", "session_id"),
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
    # embedding intentionally excluded from response


# ======================== Cluster ========================


class ClusterResponse(SpaceScopedResponse):
    name: str
    size: int
    top_subjects: list[str] = []
    top_predicates: list[str] = []
    top_objects: list[str] = []
    summary: str | None = None
    verdict: str = "UNVERIFIED"
    generation_batch: str | None = None


class ClusterDetail(ClusterResponse):
    """Cluster with its member triples."""

    triples: list[TripleResponse] = []


# ======================== Wisdom ========================


class WisdomNodeResponse(SpaceScopedResponse):
    wisdom: str
    confidence: str  # HIGH/MEDIUM/LOW
    bridge_entity: str
    cluster_ids: list[str] = []
    evidence_count: int | None = None
    tags: list[str] = []
    verified: bool = False


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


class ClusterRegenerateRequest(BaseModel):
    """Payload from cluster_pipeline.py — atomic cluster replacement."""

    clusters: list[dict]
    generated_at: str | None = None
    n_clusters: int | None = None


class WisdomRegenerateRequest(BaseModel):
    """Payload from wisdom_pipeline.py — atomic wisdom replacement."""

    wisdom_nodes: list[dict]
    generated_at: str | None = None


# ======================== Cascade Recall ========================


class CascadeRecallResult(BaseModel):
    """Multi-layer recall result."""

    wisdom: list[WisdomNodeResponse] = []  # L2
    clusters: list[ClusterResponse] = []  # L1
    triples: list[TripleResponse] = []  # L0
    blocks: list = []  # existing blocks (import MemoryBlockResponse if needed)
    layers_searched: list[str] = []  # which layers returned results
