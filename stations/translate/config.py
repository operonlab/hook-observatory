"""Translate Station configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from workshop.station_bootstrap import load_yaml_config

_yaml = load_yaml_config(
    Path(__file__).parent / "config.yaml",
    defaults={"port": 10205, "host": "127.0.0.1", "cache_ttl": 86400},
)


@dataclass(frozen=True)
class Config:
    port: int = _yaml.get("port", 10205)
    host: str = _yaml.get("host", "127.0.0.1")
    daily_budget_usd: float = float(_yaml.get("daily_budget_usd", 5.0))
    cache_ttl: int = _yaml.get("cache_ttl", 86400)
    database_url: str = _yaml.get(
        "database_url",
        "postgresql+asyncpg://joneshong:REDACTED@localhost/workshop",
    )

    # API keys from env only (never in YAML)
    deepl_api_key: str = field(
        default_factory=lambda: os.environ.get("TRANSLATE_DEEPL_API_KEY", "")
    )
    google_api_key: str = field(
        default_factory=lambda: os.environ.get("TRANSLATE_GOOGLE_API_KEY", "")
    )

    # Provider config from YAML
    providers: list = field(default_factory=lambda: _yaml.get("providers", []))


config = Config()
