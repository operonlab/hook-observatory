"""Pydantic request/response schemas for TPS Station."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=50000)
    source_lang: str = Field(default="auto", examples=["en", "ja", "auto"])
    target_lang: str = Field(default="zh-TW", examples=["zh-TW", "en", "ja"])
    provider: str | None = Field(default=None, description="Force specific provider")


class TranslateResponse(BaseModel):
    text: str
    provider: str
    source_lang: str
    target_lang: str
    cached: bool = False
    char_count: int = 0
    estimated_cost_usd: float = 0.0


class BatchTranslateRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=100)
    source_lang: str = Field(default="auto")
    target_lang: str = Field(default="zh-TW")


class BatchTranslateResponse(BaseModel):
    results: list[TranslateResponse]
    total_chars: int = 0
    total_cost_usd: float = 0.0


class UsageResponse(BaseModel):
    date: str
    providers: dict[str, ProviderUsage] = {}
    daily_budget_usd: float = 0.0
    budget_remaining_usd: float = 0.0


class ProviderUsage(BaseModel):
    char_count: int = 0
    request_count: int = 0
    estimated_cost_usd: float = 0.0


# Fix forward reference
UsageResponse.model_rebuild()
