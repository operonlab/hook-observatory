"""Pydantic models for LLM structured output — used as PydanticAI result_type."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MissedContent(BaseModel):
    text: str
    chunk: int | None = None


class AnalogContent(BaseModel):
    text: str
    chunk: int | None = None


class VerifyResult(BaseModel):
    """Result from verify/analogy extraction pass."""

    missed: list[MissedContent] = Field(default_factory=list)
    analogies: list[AnalogContent] = Field(default_factory=list)


class SynthResult(BaseModel):
    """Result from cited answer synthesis."""

    answer: str | None = None
    citations_used: list[int] = Field(default_factory=list)
    terminology_match: bool = True
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str | None = None


class ExpandedQueries(BaseModel):
    """Result from query expansion."""

    queries: list[str] = Field(default_factory=list)


class CommunitySummaryResult(BaseModel):
    """Result from community summary generation."""

    summary: str
    key_findings: list[str] = Field(default_factory=list)


class RewriteResult(BaseModel):
    """Result from corrective re-retrieval query rewrite."""

    query: str


# ── Groundedness verification models ──


class ClaimVerdict(BaseModel):
    """Single claim verification result."""

    claim: str
    supported: bool
    chunk_id: int | None = None
    explanation: str | None = None


class GroundednessResult(BaseModel):
    """Result from Tier 2 NLI-like claim verification."""

    claims: list[ClaimVerdict] = Field(default_factory=list)
    overall_grounded: bool = True
    flagged_claims: list[str] = Field(default_factory=list)


# ── Answer judge models (benchmark evaluation) ──


class AnswerJudgeSubScores(BaseModel):
    """Sub-dimensional scores for answer evaluation."""

    relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    accuracy: float = Field(default=0.0, ge=0.0, le=1.0)
    completeness: float = Field(default=0.0, ge=0.0, le=1.0)


class AnswerJudgeResult(BaseModel):
    """Result from LLM-as-Judge answer evaluation."""

    score: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""
    sub_scores: AnswerJudgeSubScores = Field(default_factory=AnswerJudgeSubScores)
