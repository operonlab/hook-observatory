"""Pydantic models for session metadata, scoring, and archive records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class SessionMeta:
    """Metadata extracted from a session JSONL file."""

    session_id: str
    project_path: str  # e.g. "-Users-joneshong-workshop"
    jsonl_path: Path
    file_size_bytes: int = 0
    event_count: int = 0
    turn_count: int = 0  # count of 'user' events
    has_companion: bool = False
    companion_path: Path | None = None
    companion_size: int = 0
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    last_modified: datetime = field(default_factory=datetime.now)
    claude_version: str | None = None
    git_branch: str | None = None
    cwd: str | None = None
    user_event_bytes: int = 0  # total bytes of 'user' events


@dataclass
class ScoreBreakdown:
    """Four-factor weighted score (0-100). Higher = more suitable for archiving."""

    total: float = 0.0
    size: float = 0.0
    age: float = 0.0
    activity: float = 0.0
    compressibility: float = 0.0


@dataclass
class ArchiveRecord:
    """Record of an archived session in the DB."""

    session_id: str
    project_path: str
    tier: str = "hot"  # hot / cold / frozen

    # Scan metadata
    file_size_bytes: int = 0
    event_count: int = 0
    turn_count: int = 0
    has_companion: bool = False
    companion_size: int = 0
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    claude_version: str | None = None
    git_branch: str | None = None
    cwd: str | None = None

    # Score
    score: float = 0.0
    score_size: float = 0.0
    score_age: float = 0.0
    score_activity: float = 0.0
    score_compress: float = 0.0

    # Archive info
    archive_path: str | None = None
    archive_type: str | None = None  # cold-archive / cold-blob
    compressed_size: int | None = None
    compression_ratio: float | None = None
    archived_at: str | None = None
    thawed_at: str | None = None
    thaw_count: int = 0

    # Summary
    summary: str | None = None

    # Housekeeping
    scanned_at: str = ""
    updated_at: str = ""


@dataclass
class ArchiveStats:
    """Aggregate statistics for status command."""

    hot_count: int = 0
    hot_size: int = 0
    warm_count: int = 0
    warm_size: int = 0
    cold_count: int = 0
    cold_original_size: int = 0
    cold_compressed_size: int = 0
    frozen_count: int = 0
    frozen_original_size: int = 0
    frozen_compressed_size: int = 0
    total_saved: int = 0
    compression_ratio: float = 0.0
