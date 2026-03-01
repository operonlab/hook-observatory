"""TOML config loader for Hook Observatory."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomli
except ModuleNotFoundError:  # Python 3.11+ stdlib
    import tomllib as tomli  # type: ignore[no-redef]


_DEFAULT_CONFIG_DIR = Path.home() / ".hook-observatory"
_DEFAULT_CONFIG_PATH = _DEFAULT_CONFIG_DIR / "config.toml"


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
    """Load config from TOML file, with env var overrides."""
    cfg = Config()
    toml_path = path or _DEFAULT_CONFIG_PATH

    if toml_path.exists():
        with open(toml_path, "rb") as f:
            raw = tomli.load(f)

        # Top-level scalars
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

        # [spool] section
        spool_raw = raw.get("spool", {})
        if "dir" in spool_raw:
            cfg.spool.dir = Path(os.path.expanduser(str(spool_raw["dir"])))
        if "drain_interval" in spool_raw:
            cfg.spool.drain_interval = float(spool_raw["drain_interval"])
        if "batch_size" in spool_raw:
            cfg.spool.batch_size = int(spool_raw["batch_size"])

    # Env var overrides
    if v := os.environ.get("HOOK_OBS_PORT"):
        cfg.port = int(v)
    if v := os.environ.get("HOOK_OBS_HOST"):
        cfg.host = v
    if v := os.environ.get("HOOK_OBS_DATABASE_URL"):
        cfg.database_url = v
    if v := os.environ.get("HOOK_OBS_SECRET_KEY"):
        cfg.secret_key = v

    return cfg


config = load_config()
