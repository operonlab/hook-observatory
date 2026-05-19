"""DocVault Pydantic schemas — request/response types."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.shared.schemas import PaginatedResponse, SpaceScopedResponse  # noqa: F401

# ======================== Document ========================


class DocumentCreate(BaseModel):
    title: str = Field(..., max_length=500)
    source_type: str = Field(default="markdown", pattern="^(pdf|docx|markdown|webpage|api|audio|video)$")
    source_uri: str | None = None
    content_hash: str = Field(..., max_length=64)
    tags: list[str] = Field(default_factory=list)
    metadata_: dict | None = Field(default=None, alias="metadata")


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = None
    metadata_: dict | None = Field(default=None, alias="metadata")
    status: str | None = Field(
        default=None, pattern="^(ingested|processing|indexed|enriched|published|archived|failed)$"
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class DocumentResponse(SpaceScopedResponse):
    title: str
    source_type: str
    source_uri: str | None = None
    content_hash: str
    current_version_id: str | None = None
    tags: list[str] = []
    metadata_: dict | None = Field(default=None, alias="metadata")
    status: str
    confidence: float | None = None
    access_count: int = 0
    last_accessed_at: datetime | None = None

    model_config = {"populate_by_name": True}


class DocumentBrief(BaseModel):
    """Lightweight document for list views."""

    id: str
    title: str
    source_type: str
    tags: list[str] = []
    status: str
    created_at: datetime


# ======================== DocumentVersion ========================


class DocumentVersionCreate(BaseModel):
    document_id: str
    version_number: int
    content_hash: str = Field(..., max_length=64)
    raw_content: str | None = None
    extraction_model: str | None = None


class DocumentVersionUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(processing|ready|superseded)$")
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
    # raw_content intentionally excluded from response (too large)


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
    chunk_type: str = Field(default="text", pattern="^(text|table|list|code)$")
    source_role: str | None = None
    doc_weight: float | None = None


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
    source_role: str | None = None
    doc_weight: float | None = None


# ======================== DocumentRelation ========================


class DocumentRelationCreate(BaseModel):
    source_document_id: str
    target_document_id: str
    relation_type: str = Field(..., pattern="^(cites|extends|contradicts|supersedes|related)$")
    evidence: str | None = None
    source_chunk_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class DocumentRelationUpdate(BaseModel):
    evidence: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    invalid_at: datetime | None = None
    invalidated_by: str | None = None


class DocumentRelationResponse(SpaceScopedResponse):
    source_document_id: str
    target_document_id: str
    relation_type: str
    evidence: str | None = None
    source_chunk_id: str | None = None
    confidence: float | None = None
    valid_from: datetime | None = None
    invalid_at: datetime | None = None
    invalidated_by: str | None = None


# ======================== CoverageGap ========================


class CoverageGapCreate(BaseModel):
    query_text: str
    query_hash: str = Field(..., max_length=64)
    detected_at: datetime
    gap_type: str = Field(..., pattern="^(topic_missing|depth_insufficient|outdated)$")
    suggested_sources: dict | None = None


class CoverageGapUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(pending|investigating|resolved|dismissed)$")
    resolution: str | None = Field(
        default=None, pattern="^(document_added|not_applicable|merged_existing)$"
    )
    resolved_document_id: str | None = None
    suggested_sources: dict | None = None


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
    query_hash: str = Field(..., max_length=64)
    answer_text: str
    citations: dict | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    crag_verdict: str | None = Field(default=None, pattern="^(correct|ambiguous|incorrect)$")
    pipeline_used: str = Field(default="A", pattern="^(A|B|C|cache)$")
    latency_ms: int | None = None
    session_id: str | None = Field(default=None, max_length=64)
    turn_number: int | None = None


class QALogResponse(SpaceScopedResponse):
    query_text: str
    query_hash: str
    answer_text: str
    citations: dict | None = None
    confidence: float | None = None
    crag_verdict: str | None = None
    feedback: str | None = None
    pipeline_used: str = "A"
    latency_ms: int | None = None
    session_id: str | None = None
    turn_number: int | None = None


class QAFeedbackUpdate(BaseModel):
    """Lightweight feedback schema for QA log entries."""

    feedback: str = Field(..., pattern="^(positive|negative)$")


# ======================== Upload ========================


class DocumentUploadRequest(BaseModel):
    """Upload request — server-side file parsing."""

    file_path: str = Field(..., description="Absolute path to the local file")
    title: str | None = Field(default=None, max_length=500)
    source_type: str | None = Field(default=None, pattern="^(pdf|docx|markdown|webpage|api|audio|video)$")
    source_uri: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict | None = None


# ======================== Search / QA Request ========================


class SearchChunkResult(BaseModel):
    """A single search result chunk."""

    document_id: str
    score: float
    content: str
    section_path: str | None = None
    page_range: str | None = None
    heading: str | None = None
    chunk_index: int | None = None


class DocumentSearchResponse(BaseModel):
    """Search response with results."""

    query: str
    results: list[SearchChunkResult] = []
    total: int = 0


class DocumentSearchParams(BaseModel):
    q: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=100)
    source_type: str | None = None
    tags: list[str] | None = None


class QARequest(BaseModel):
    """Question-answering request for Pipeline A/B/C."""

    question: str = Field(..., min_length=1, max_length=2000)
    mode: str = Field(default="factual", pattern="^(factual|mixed)$")
    domain: str = Field(default="default")
    top_k: int = Field(default=20, ge=1, le=50)
    session_id: str | None = Field(default=None, max_length=64)
    tags: list[str] | None = Field(
        default=None,
        description="Optional: filter chunks whose payload tags contain ALL of these values",
    )


class CitationRef(BaseModel):
    """A single citation reference in a QA answer."""

    index: int | None = None
    document_id: str
    chunk_id: str | None = None
    section: str | None = None
    page: str | None = None
    quote: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # 0.0-1.0 retrieval/synth 信心分數
    confidence_type: Literal["extracted", "inferred", "ambiguous"] | None = None
    # 三段式證據強度（graphify-cannibalized 2026-05-11）
    # extracted=quote 直接出現原文 | inferred=LLM 推斷 | ambiguous=多源模糊
    source_role: str | None = None
    doc_weight: float | None = None
    # Authority-aware retrieval metadata surfaced for client inspection (Phase 1).
    role_warning: bool | None = None
    # P2.3: true when this citation is a fallback chunk used as the primary
    # answer source while contradicting authoritative chunks were also present.


class QAResponse(BaseModel):
    """Response from the QA pipeline."""

    question: str
    answer: str
    citations: list[CitationRef] = []
    confidence: float | None = None
    crag_verdict: str | None = None
    pipeline_used: str = "A"
    qa_log_id: str | None = None
    session_id: str | None = None
    turn_number: int | None = None


# ======================== PreGeneratedQA ========================


class PreGeneratedQAResponse(SpaceScopedResponse):
    document_id: str
    version_id: str
    question: str
    answer: str
    question_type: str = "factual"
    source_chunks: dict | None = None
    confidence: float = 0.0
    status: str = "pending"
    reuse_count: int = 0


# ======================== Dashboard ========================


class DocvaultDashboardResponse(BaseModel):
    total_documents: int = 0
    total_chunks: int = 0
    total_qa_logs: int = 0
    coverage_gap_count: int = 0
    published_count: int = 0
    recent_documents: list[DocumentBrief] = []
