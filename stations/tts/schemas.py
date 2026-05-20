"""Pydantic schemas for /v2/* endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SynthesizeReqModel(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    lang: str = Field(..., pattern="^(zh|en|ja|ko|auto)$")
    voice_id: str = "master"
    output: str = Field("file", pattern="^(file|buffer|numpy|tensor|base64|stream)$")
    output_path: str | None = None
    target_sample_rate: int | None = Field(None, ge=8000, le=48000)
    speed: float = Field(1.0, ge=0.5, le=2.0)
    engine: str = "auto"
    mode: str | None = Field(None, pattern="^(quality|live)$")
    engine_specific: dict[str, Any] = Field(default_factory=dict)


class SynthesizeResultModel(BaseModel):
    duration_s: float
    sample_rate: int
    rtf: float
    engine: str
    output_mode: str
    audio_path: str | None = None
    audio_base64: str | None = None
    audio_bytes_b64: str | None = None  # MCP wire format only


class EngineInfoModel(BaseModel):
    name: str
    languages: list[str]
    multi_speaker: bool
    rtf_typical: float
    vram_mb: int
    needs_wsl: bool
    needs_gpu: bool
    supported_outputs: list[str]
    sample_rate: int
    loaded: bool
    idle_sec: float | None = None
    notes: str = ""
