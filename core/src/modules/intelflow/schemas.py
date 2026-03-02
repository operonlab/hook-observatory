"""Intelflow Pydantic schemas — request/response types."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from src.shared.schemas import SpaceScopedResponse

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


# ======================== Briefing Topic ========================


class BriefingTopicCreate(BaseModel):
    name: str
    display_name: str
    description: str | None = None
    enabled: bool = True
    priority: int = 0
    prompt_template: str | None = None
    sources: list[dict] = Field(default_factory=list)
    schedule: str = "daily"


class BriefingTopicUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    prompt_template: str | None = None
    sources: list[dict] | None = None
    schedule: str | None = None


class BriefingSubtopicResponse(SpaceScopedResponse):
    topic_id: str
    name: str
    parameters: dict = {}
    enabled: bool = True


class BriefingTopicResponse(SpaceScopedResponse):
    name: str
    display_name: str
    description: str | None = None
    enabled: bool = True
    priority: int = 0
    prompt_template: str | None = None
    sources: list[dict] = []
    schedule: str = "daily"
    subtopics: list[BriefingSubtopicResponse] = []


# ======================== Briefing Subtopic ========================


class BriefingSubtopicCreate(BaseModel):
    name: str
    parameters: dict = Field(default_factory=dict)
    enabled: bool = True


class BriefingSubtopicUpdate(BaseModel):
    name: str | None = None
    parameters: dict | None = None
    enabled: bool | None = None


# ======================== Briefing ========================


class BriefingCreate(BaseModel):
    date: date
    topic_id: str | None = None
    domain: str
    raw_data: dict | None = None
    analyses: dict | None = None
    debate: str | None = None


class BriefingResponse(SpaceScopedResponse):
    date: date
    topic_id: str | None = None
    domain: str
    raw_data: dict | None = None
    analyses: dict | None = None
    debate: str | None = None


# ======================== Search ========================


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    limit: int = Field(default=10, ge=1, le=100)
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class SearchCheckRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    threshold: float = Field(default=0.85, ge=0.0, le=1.0)


class SearchCheckResponse(BaseModel):
    exists: bool
    matches: list["SearchMatchResult"] = []


class SearchMatchResult(BaseModel):
    report: ReportBrief
    score: float


class SemanticSearchResult(BaseModel):
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
    total_briefings: int = 0
    recent_reports: list[ReportBrief] = []


class TimelineEntry(BaseModel):
    date: date
    count: int


class TimelineResponse(BaseModel):
    entries: list[TimelineEntry] = []
