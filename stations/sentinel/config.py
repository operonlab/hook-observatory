"""YAML config loader for Workshop Sentinel."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from workshop.station_bootstrap import load_yaml_config

_CONFIG_PATH = Path(__file__).parent / "config.yaml"

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
    deep_interval: float = 600.0  # 10 minutes (was 5m, too aggressive)
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
    login_url: str = "/login"
    spool: SpoolConfig = field(default_factory=SpoolConfig)
    check: CheckConfig = field(default_factory=CheckConfig)
    lock_dir: Path = field(default_factory=lambda: LOCK_DIR)


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
    if "login_url" in raw:
        cfg.login_url = str(raw["login_url"])
    if "lock_dir" in raw:
        cfg.lock_dir = Path(raw["lock_dir"])

    # Spool sub-config (flat keys: spool_*)
    if "spool_dir" in raw:
        cfg.spool.dir = Path(raw["spool_dir"])
    if "spool_drain_interval" in raw:
        cfg.spool.drain_interval = float(raw["spool_drain_interval"])
    if "spool_batch_size" in raw:
        cfg.spool.batch_size = int(raw["spool_batch_size"])

    # Check sub-config (flat keys: check_*)
    if "check_light_interval" in raw:
        cfg.check.light_interval = float(raw["check_light_interval"])
    if "check_deep_interval" in raw:
        cfg.check.deep_interval = float(raw["check_deep_interval"])
    if "check_intervention_delay" in raw:
        cfg.check.intervention_delay = float(raw["check_intervention_delay"])
    if "check_repair_timeout" in raw:
        cfg.check.repair_timeout = float(raw["check_repair_timeout"])

    return cfg


config = load_config()
