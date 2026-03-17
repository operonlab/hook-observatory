"""YAML config loader for Hook Observatory."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from workshop.station_bootstrap import load_yaml_config

_DEFAULT_CONFIG_DIR = Path.home() / ".hook-observatory"
_CONFIG_PATH = Path(__file__).parent / "config.yaml"


@dataclass
class SpoolConfig:
    dir: Path = field(default_factory=lambda: _DEFAULT_CONFIG_DIR / "spool")
    drain_interval: float = 2.0
    batch_size: int = 100


@dataclass
class Config:
    port: int = 4100
    host: str = "127.0.0.1"
    database_url: str = "postgresql+asyncpg://joneshong:dev_12345@localhost/workshop"
    secret_key: str = "change-me-in-production"
    session_cookie_name: str = "workshop_session"
    session_max_age: int = 604800  # 7 days
    spool: SpoolConfig = field(default_factory=SpoolConfig)

    @property
    def spool_dir(self) -> Path:
        return self.spool.dir


def load_config(path: Path | None = None) -> Config:
    """Load config from YAML file, with env var overrides."""
    raw = load_yaml_config(path or _CONFIG_PATH)

    cfg = Config()
    if "port" in raw:
        cfg.port = int(raw["port"])
    if "host" in raw:
        cfg.host = str(raw["host"])
    if "database_url" in raw:
        cfg.database_url = str(raw["database_url"])
    if "secret_key" in raw:
        cfg.secret_key = str(raw["secret_key"])
    if "session_cookie_name" in raw:
        cfg.session_cookie_name = str(raw["session_cookie_name"])
    if "session_max_age" in raw:
        cfg.session_max_age = int(raw["session_max_age"])

    # Spool sub-config (flat keys: spool_*)
    if "spool_dir" in raw:
        cfg.spool.dir = Path(os.path.expanduser(str(raw["spool_dir"])))
    if "spool_drain_interval" in raw:
        cfg.spool.drain_interval = float(raw["spool_drain_interval"])
    if "spool_batch_size" in raw:
        cfg.spool.batch_size = int(raw["spool_batch_size"])

    return cfg


config = load_config()
