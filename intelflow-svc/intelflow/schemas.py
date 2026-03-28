"""Intelflow Pydantic schemas — request/response types.

Standalone variant:
- Removed SearchRequest/SemanticSearchResult (Qdrant-dependent)
- Removed SynthesizeRequest/Response (RLM-dependent)
- Kept basic CRUD schemas + dashboard + text search
"""

from datetime import date, datetime

from pydantic import BaseModel, Field

from shared.schemas import SpaceScopedResponse

# ======================== Report ========================


class ReportCreate(BaseModel):
    title: str
    query: str
    content: str
    sources: list[dict] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    skill_name: str | None = None
    created_at: datetime | None = Field(
        None, description="Override creation timestamp (for migration)"
    )


class ReportUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    sources: list[dict] | None = None
    tags: list[str] | None = None


class ReportResponse(SpaceScopedResponse):
    title: str
    query: str
    content: str
    sources: list[dict] = []
    tags: list[str] = []
    skill_name: str | None = None
    topics: list["TopicBrief"] = []


class ReportBrief(BaseModel):
    """Lightweight report for search results."""

    id: str
    title: str
    query: str
    tags: list[str] = []
    skill_name: str | None = None
    created_at: datetime


# ======================== Topic ========================


class TopicCreate(BaseModel):
    name: str
    display_name: str | None = None


class TopicResponse(SpaceScopedResponse):
    name: str
    display_name: str | None = None
    report_count: int = 0


class TopicBrief(BaseModel):
    id: str
    name: str
    display_name: str | None = None


class TopicGraphNode(BaseModel):
    id: str
    name: str
    display_name: str | None = None
    report_count: int = 0


class TopicGraphEdge(BaseModel):
    source: str
    target: str
    weight: float = 1.0


class TopicGraphResponse(BaseModel):
    nodes: list[TopicGraphNode]
    edges: list[TopicGraphEdge]


# ======================== Text Search ========================


class TextSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    limit: int = Field(default=10, ge=1, le=100)


class TextSearchResult(BaseModel):
    report: ReportBrief
    score: float


# ======================== Search Session ========================


class SearchSessionResponse(SpaceScopedResponse):
    query: str
    source: str | None = None
    result_type: str | None = None
    report_id: str | None = None


# ======================== Dashboard ========================


class DashboardResponse(BaseModel):
    total_reports: int = 0
    total_topics: int = 0
    recent_reports: list[ReportBrief] = []


class TimelineEntry(BaseModel):
    date: date
    count: int


class TimelineResponse(BaseModel):
    entries: list[TimelineEntry] = []
