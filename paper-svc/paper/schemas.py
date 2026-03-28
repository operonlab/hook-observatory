"""Paper module Pydantic schemas — request/response types.

Adapted from core/src/modules/paper/schemas.py for standalone service.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from svc_shared.schemas import SpaceScopedResponse

# ======================== Article ========================


class ArticleCreate(BaseModel):
    title: str
    abstract: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None
    year: int | None = None
    authors: list[dict] = Field(default_factory=list)
    journal: str | None = None
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    pdf_url: str | None = None
    source_url: str | None = None
    full_text: str | None = None
    s3_uri: str | None = None


class ArticleUpdate(BaseModel):
    title: str | None = None
    abstract: str | None = None
    doi: str | None = None
    year: int | None = None
    authors: list[dict] | None = None
    journal: str | None = None
    categories: list[str] | None = None
    tags: list[str] | None = None
    pdf_url: str | None = None
    source_url: str | None = None
    full_text: str | None = None
    s3_uri: str | None = None


class ArticleBrief(BaseModel):
    id: str
    title: str
    arxiv_id: str | None = None
    doi: str | None = None
    year: int | None = None
    authors: list[dict] = []
    categories: list[str] = []
    tags: list[str] = []
    created_at: datetime


class ArticleResponse(SpaceScopedResponse):
    title: str
    abstract: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None
    year: int | None = None
    authors: list[dict] = []
    journal: str | None = None
    categories: list[str] = []
    tags: list[str] = []
    pdf_url: str | None = None
    source_url: str | None = None
    full_text: str | None = None
    s3_uri: str | None = None
    digest: "DigestResponse | None" = None


# ======================== Digest ========================


class DigestCreate(BaseModel):
    paper_id: str
    one_liner: str | None = None
    key_findings: list[str] = Field(default_factory=list)
    workshop_relevance: str | None = None
    applicable_modules: list[str] = Field(default_factory=list)
    actionable_insight: str | None = None
    effort_estimate: str | None = None
    confidence: float | None = None
    model_used: str | None = None
    generated_at: datetime | None = None


class DigestUpdate(BaseModel):
    one_liner: str | None = None
    key_findings: list[str] | None = None
    workshop_relevance: str | None = None
    applicable_modules: list[str] | None = None
    actionable_insight: str | None = None
    effort_estimate: str | None = None
    confidence: float | None = None
    model_used: str | None = None
    generated_at: datetime | None = None


class DigestResponse(SpaceScopedResponse):
    paper_id: str
    one_liner: str | None = None
    key_findings: list[str] = []
    workshop_relevance: str | None = None
    applicable_modules: list[str] = []
    actionable_insight: str | None = None
    effort_estimate: str | None = None
    confidence: float | None = None
    model_used: str | None = None
    generated_at: datetime | None = None


# ======================== Annotation ========================


class AnnotationCreate(BaseModel):
    note: str
    annotation_type: str = "note"
    tags: list[str] = Field(default_factory=list)


class AnnotationUpdate(BaseModel):
    note: str | None = None
    annotation_type: str | None = None
    tags: list[str] | None = None


class AnnotationResponse(SpaceScopedResponse):
    paper_id: str
    note: str
    annotation_type: str
    tags: list[str] = []


# ======================== Dashboard ========================


class DashboardResponse(BaseModel):
    total_articles: int = 0
    total_digests: int = 0
    total_annotations: int = 0
    high_relevance_count: int = 0
    recent_articles: list[ArticleBrief] = []
