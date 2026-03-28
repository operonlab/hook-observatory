"""YAML config loader for Anvil Station."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sdk_client.station_bootstrap import load_yaml_config

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"


@dataclass
class Config:
    port: int = 4103
    host: str = "127.0.0.1"
    database_url: str = "postgresql+asyncpg://joneshong:REDACTED@localhost/workshop"
    skills_dir: Path = Path.home() / ".claude" / "skills"


def load_config(path: Path | None = None) -> Config:
    """Load config from YAML file, with env var overrides."""
    yaml_path = path or _DEFAULT_CONFIG_PATH
    raw = load_yaml_config(
        yaml_path,
        defaults={
            "port": 4103,
            "host": "127.0.0.1",
            "database_url": "postgresql+asyncpg://joneshong:REDACTED@localhost/workshop",
            "skills_dir": str(Path.home() / ".claude" / "skills"),
        },
    )

    return Config(
        port=int(raw["port"]),
        host=str(raw["host"]),
        database_url=str(raw["database_url"]),
        skills_dir=Path(os.path.expanduser(str(raw["skills_dir"]))),
    )


config = load_config()
