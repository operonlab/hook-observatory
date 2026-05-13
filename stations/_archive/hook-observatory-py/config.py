"""YAML config loader for Hook Observatory."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_yaml_config(config_path: Path | str, defaults: dict | None = None) -> dict:
    """Load YAML config with env var override.

    Priority: env vars > YAML file > defaults.
    Env var naming: <ENV_PREFIX>_<KEY> (env_prefix from YAML).
    """
    import yaml

    result: dict = dict(defaults or {})
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            file_config = yaml.safe_load(f) or {}
        result.update(file_config)

    env_prefix = result.get("env_prefix", "").upper()
    if env_prefix and not env_prefix.endswith("_"):
        env_prefix += "_"
    for key in list(result.keys()):
        if key == "env_prefix":
            continue
        env_key = f"{env_prefix}{key.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            if env_val.isdigit():
                result[key] = int(env_val)
            elif env_val.lower() in ("true", "false"):
                result[key] = env_val.lower() == "true"
            else:
                result[key] = env_val
    return result

_DEFAULT_CONFIG_DIR = Path.home() / ".hook-observatory"
_CONFIG_PATH = Path(__file__).parent / "config.yaml"


@dataclass
class SpoolConfig:
    dir: Path = field(default_factory=lambda: _DEFAULT_CONFIG_DIR / "spool")
    drain_interval: float = 2.0
    batch_size: int = 100


@dataclass
class Config:
    port: int = 10100
    host: str = "127.0.0.1"
    database_url: str = "sqlite+aiosqlite:///~/.hook-observatory/events.db"
    secret_key: str = "change-me-in-production"  # noqa: S105
    session_cookie_name: str = "workshop_session"
    session_max_age: int = 604800  # 7 days
    auth_enabled: bool = False
    spool: SpoolConfig = field(default_factory=SpoolConfig)

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

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

    if "auth_enabled" in raw:
        cfg.auth_enabled = bool(raw["auth_enabled"])

    # Spool sub-config (flat keys: spool_*)
    if "spool_dir" in raw:
        cfg.spool.dir = Path(os.path.expanduser(str(raw["spool_dir"])))
    if "spool_drain_interval" in raw:
        cfg.spool.drain_interval = float(raw["spool_drain_interval"])
    if "spool_batch_size" in raw:
        cfg.spool.batch_size = int(raw["spool_batch_size"])

    return cfg


config = load_config()
