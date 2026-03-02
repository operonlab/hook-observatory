"""Configuration loader — JSON config + env overrides."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path.home() / ".claude" / "data" / "session-archiver"
CONFIG_PATH = DATA_DIR / "config.json"

# Defaults
_DEFAULTS = {
    "projects_dir": str(Path.home() / ".claude" / "projects"),
    "archive_dir": str(Path.home() / ".claude" / "archive" / "cold"),
    "database_url": "postgresql://localhost:5432/workshop",
    "db_schema": "workshop_session_archive",
    "score_threshold": 70,
    "archive_min_age_days": 3,
    "compression_level": 9,
    "ollama_url": "http://localhost:11434",
    "ollama_model": "nomic-embed-text",
    "embedding_dim": 768,
}


@dataclass
class Config:
    """Session Archiver configuration."""

    projects_dir: str = _DEFAULTS["projects_dir"]
    archive_dir: str = _DEFAULTS["archive_dir"]
    database_url: str = _DEFAULTS["database_url"]
    db_schema: str = _DEFAULTS["db_schema"]
    score_threshold: int = _DEFAULTS["score_threshold"]
    archive_min_age_days: int = _DEFAULTS["archive_min_age_days"]
    compression_level: int = _DEFAULTS["compression_level"]
    ollama_url: str = _DEFAULTS["ollama_url"]
    ollama_model: str = _DEFAULTS["ollama_model"]
    embedding_dim: int = _DEFAULTS["embedding_dim"]


def load_config() -> Config:
    """Load config from JSON file with env var overrides.

    Priority: env vars > config.json > defaults.
    Env vars use SESSION_ARCHIVER_ prefix (e.g. SESSION_ARCHIVER_SCORE_THRESHOLD=50).
    """
    data = dict(_DEFAULTS)

    # Layer 1: JSON file
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            file_data = json.load(f)
        data.update(file_data)

    # Layer 2: Env var overrides
    prefix = "SESSION_ARCHIVER_"
    for key in _DEFAULTS:
        env_key = prefix + key.upper()
        env_val = os.environ.get(env_key)
        if env_val is not None:
            # Coerce to the right type
            default_val = _DEFAULTS[key]
            if isinstance(default_val, int):
                data[key] = int(env_val)
            else:
                data[key] = env_val

    return Config(**data)
