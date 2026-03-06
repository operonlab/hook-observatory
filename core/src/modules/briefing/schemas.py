"""Briefing Pydantic schemas — request/response types."""

from datetime import date

from pydantic import BaseModel, Field

from src.shared.schemas import SpaceScopedResponse

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


# ======================== Briefing Analyst ========================


class AnalystCreate(BaseModel):
    name: str
    display_name: str
    color: str = "#c4a7e7"
    model_id: str | None = None
    system_prompt: str | None = None


class AnalystUpdate(BaseModel):
    display_name: str | None = None
    color: str | None = None
    avatar_url: str | None = None
    model_id: str | None = None
    system_prompt: str | None = None
    enabled: bool | None = None
    priority: int | None = None


class AnalystResponse(SpaceScopedResponse):
    name: str
    display_name: str
    color: str
    avatar_url: str | None = None
    model_id: str | None = None
    system_prompt: str | None = None
    enabled: bool = True
    priority: int = 0


# ======================== Briefing Entry ========================


class BriefingEntryCreate(BaseModel):
    phase: str  # raw | analysis | debate | conclusion
    key: str
    content: str
    metadata: dict = Field(default_factory=dict)


class BriefingEntryResponse(SpaceScopedResponse):
    briefing_id: str
    phase: str
    key: str
    content: str
    metadata: dict = {}


# ======================== Briefing ========================


class BriefingCreate(BaseModel):
    date: date
    topic_id: str | None = None
    domain: str
    status: str = "searching"
    raw_data: dict | None = None
    analyses: dict | None = None
    debate: str | None = None


class BriefingUpdate(BaseModel):
    status: str | None = None


class BriefingResponse(SpaceScopedResponse):
    date: date
    topic_id: str | None = None
    domain: str
    status: str = "searching"
    raw_data: dict | None = None
    analyses: dict | None = None
    debate: str | None = None
    entries: list[BriefingEntryResponse] = []
    conclusion: str | None = None
    conclusion_meta: dict | None = None
    follow_ups: list["FollowUpResponse"] = []


# ======================== Follow-Up ========================


class FollowUpCreate(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class FollowUpResponse(SpaceScopedResponse):
    briefing_id: str
    question: str
    answer: str | None = None
    status: str = "pending"
    metadata: dict = {}


# ======================== Daily Summary ========================


class DomainSummary(BaseModel):
    domain: str
    display_name: str
    briefing_id: str
    status: str
    sources_count: int = 0
    analysts_count: int = 0
    has_conclusion: bool = False


class DailySummaryResponse(BaseModel):
    date: date
    status: str
    domains: list[DomainSummary] = []
    merged_conclusion: str | None = None
    consensus_points: list[str] = []
    dissent_points: list[dict] = []
    confidence: float | None = None
    briefing_ids: list[str] = []
    follow_up_count: int = 0
