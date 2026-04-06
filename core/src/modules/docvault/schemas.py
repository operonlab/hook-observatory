"""DocVault Pydantic schemas — request/response types."""

from datetime import datetime

from pydantic import BaseModel, Field

from src.shared.schemas import PaginatedResponse, SpaceScopedResponse  # noqa: F401

# ======================== Document ========================


class DocumentCreate(BaseModel):
    title: str
    source_type: str = "pdf"
    source_uri: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict | None = None


class DocumentUpdate(BaseModel):
    title: str | None = None
    tags: list[str] | None = None
    metadata: dict | None = None
    status: str | None = None


class DocumentResponse(SpaceScopedResponse):
    title: str
    source_type: str
    source_uri: str | None = None
    content_hash: str
    current_version_id: str | None = None
    tags: list[str] = []
    metadata: dict | None = None
    status: str
    confidence: float = 0.0
    access_count: int = 0
    last_accessed_at: datetime | None = None


# ======================== DocumentVersion ========================


class DocumentVersionCreate(BaseModel):
    document_id: str
    version_number: int
    content_hash: str
    raw_content: str | None = None
    extraction_model: str | None = None


class DocumentVersionUpdate(BaseModel):
    status: str | None = None
    chunk_count: int | None = None
    summary: str | None = None
    table_of_contents: dict | None = None


class DocumentVersionResponse(SpaceScopedResponse):
    document_id: str
    version_number: int
    content_hash: str
    status: str
    chunk_count: int = 0
    extraction_model: str | None = None
    summary: str | None = None
    table_of_contents: dict | None = None


# ======================== DocumentChunk ========================


class DocumentChunkCreate(BaseModel):
    version_id: str
    document_id: str
    chunk_index: int
    content: str
    section_path: str | None = None
    page_range: str | None = None
    heading: str | None = None
    token_count: int = 0
    chunk_type: str = "text"


class DocumentChunkResponse(SpaceScopedResponse):
    version_id: str
    document_id: str
    chunk_index: int
    content: str
    section_path: str | None = None
    page_range: str | None = None
    heading: str | None = None
    token_count: int = 0
    chunk_type: str = "text"


# ======================== DocumentRelation ========================


class DocumentRelationCreate(BaseModel):
    source_document_id: str
    target_document_id: str
    relation_type: str
    evidence: str | None = None
    source_chunk_id: str | None = None
    confidence: float = 0.0


class DocumentRelationResponse(SpaceScopedResponse):
    source_document_id: str
    target_document_id: str
    relation_type: str
    evidence: str | None = None
    source_chunk_id: str | None = None
    confidence: float = 0.0
    valid_from: datetime | None = None
    invalid_at: datetime | None = None
    invalidated_by: str | None = None


# ======================== CoverageGap ========================


class CoverageGapCreate(BaseModel):
    query_text: str
    query_hash: str
    gap_type: str
    suggested_sources: dict | None = None


class CoverageGapUpdate(BaseModel):
    status: str | None = None
    resolution: str | None = None
    resolved_document_id: str | None = None


class CoverageGapResponse(SpaceScopedResponse):
    query_text: str
    query_hash: str
    detected_at: datetime
    gap_type: str
    status: str
    resolution: str | None = None
    resolved_document_id: str | None = None
    suggested_sources: dict | None = None


# ======================== QALog ========================


class QALogCreate(BaseModel):
    query_text: str
    query_hash: str
    answer_text: str
    citations: dict | None = None
    confidence: float = 0.0
    crag_verdict: str | None = None
    pipeline_used: str = "A"
    latency_ms: int = 0


class QALogResponse(SpaceScopedResponse):
    query_text: str
    query_hash: str
    answer_text: str
    citations: dict | None = None
    confidence: float = 0.0
    crag_verdict: str | None = None
    feedback: str | None = None
    pipeline_used: str = "A"
    latency_ms: int = 0


# ======================== QA Request/Response ========================


class QARequest(BaseModel):
    question: str
    mode: str = "factual"  # factual | mixed
    top_k: int = 5
    domain: str = "default"


class Citation(BaseModel):
    document_id: str
    chunk_id: str
    section: str | None = None
    page: str | None = None
    quote: str | None = None
    score: float = 0.0


class QAResponse(BaseModel):
    answer: str
    citations: list[Citation] = []
    confidence: float = 0.0
    crag_verdict: str | None = None
    pipeline_used: str = "A"
    latency_ms: int = 0


class GapStats(BaseModel):
    total: int = 0
    pending: int = 0
    investigating: int = 0
    resolved: int = 0
    dismissed: int = 0


class DocvaultStats(BaseModel):
    total_documents: int = 0
    total_chunks: int = 0
    total_relations: int = 0
    total_gaps: int = 0
    total_qa_logs: int = 0
    by_status: dict[str, int] = {}
    by_source_type: dict[str, int] = {}
