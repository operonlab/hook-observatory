"""TOML config loader for Workshop Sentinel."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomli
except ModuleNotFoundError:
    import tomllib as tomli  # type: ignore[no-redef]


_DEFAULT_CONFIG_DIR = Path.home() / ".sentinel"
_DEFAULT_CONFIG_PATH = _DEFAULT_CONFIG_DIR / "config.toml"

LOCK_DIR = Path("/opt/homebrew/var/run/workshop/sentinel")
SPOOL_DIR = Path("/opt/homebrew/var/log/workshop/sentinel")


@dataclass
class SpoolConfig:
    dir: Path = field(default_factory=lambda: SPOOL_DIR)
    drain_interval: float = 5.0
    batch_size: int = 50


@dataclass
class CheckConfig:
    light_interval: float = 30.0
    deep_interval: float = 300.0
    intervention_delay: float = 300.0  # 5 minutes
    repair_timeout: float = 600.0  # 10 minutes


@dataclass
class Config:
    port: int = 4101
    host: str = "127.0.0.1"
    database_url: str = "postgresql+asyncpg://joneshong:dev_12345@localhost/workshop"
    secret_key: str = "change-me-in-production"
    session_cookie_name: str = "workshop_session"
    session_max_age: int = 604800  # 7 days
    login_url: str = "/v2/login"
    spool: SpoolConfig = field(default_factory=SpoolConfig)
    check: CheckConfig = field(default_factory=CheckConfig)
    lock_dir: Path = field(default_factory=lambda: LOCK_DIR)


def load_config(path: Path | None = None) -> Config:
    """Load config from TOML file, with env var overrides."""
    cfg = Config()
    toml_path = path or _DEFAULT_CONFIG_PATH

    if toml_path.exists():
        with open(toml_path, "rb") as f:
            raw = tomli.load(f)

        if "port" in raw:
            cfg.port = int(raw["port"])
        if "host" in raw:
            cfg.host = str(raw["host"])
        if "database_url" in raw:
            cfg.database_url = str(raw["database_url"])

        spool_raw = raw.get("spool", {})
        if "dir" in spool_raw:
            cfg.spool.dir = Path(os.path.expanduser(str(spool_raw["dir"])))
        if "drain_interval" in spool_raw:
            cfg.spool.drain_interval = float(spool_raw["drain_interval"])

        check_raw = raw.get("check", {})
        if "light_interval" in check_raw:
            cfg.check.light_interval = float(check_raw["light_interval"])
        if "deep_interval" in check_raw:
            cfg.check.deep_interval = float(check_raw["deep_interval"])
        if "intervention_delay" in check_raw:
            cfg.check.intervention_delay = float(check_raw["intervention_delay"])

    # Env var overrides
    if v := os.environ.get("SENTINEL_PORT"):
        cfg.port = int(v)
    if v := os.environ.get("SENTINEL_HOST"):
        cfg.host = v
    if v := os.environ.get("SENTINEL_DATABASE_URL"):
        cfg.database_url = v
    if v := os.environ.get("SENTINEL_SECRET_KEY"):
        cfg.secret_key = v
    if v := os.environ.get("CORE_SECRET_KEY"):
        cfg.secret_key = v

    return cfg


config = load_config()
