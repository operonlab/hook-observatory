"""TPS Station configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from workshop.station_bootstrap import load_yaml_config

_yaml = load_yaml_config(
    Path(__file__).parent / "config.yaml",
    defaults={"port": 4114, "host": "127.0.0.1", "cache_ttl": 2592000},
)


@dataclass(frozen=True)
class Config:
    port: int = _yaml.get("port", 4114)
    host: str = _yaml.get("host", "127.0.0.1")
    daily_budget_usd: float = float(_yaml.get("daily_budget_usd", 5.0))
    cache_ttl: int = _yaml.get("cache_ttl", 2592000)
    redis_url: str = _yaml.get("redis_url", "redis://127.0.0.1:6379/0")

    # API keys from env only (never in YAML)
    deepl_api_key: str = field(default_factory=lambda: os.environ.get("TPS_DEEPL_API_KEY", ""))
    google_project_id: str = field(
        default_factory=lambda: os.environ.get("TPS_GOOGLE_PROJECT_ID", "")
    )

    # Provider config from YAML
    providers: list = field(default_factory=lambda: _yaml.get("providers", []))


config = Config()
