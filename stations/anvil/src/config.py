"""TOML config loader for Anvil Station."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    import tomli
except ModuleNotFoundError:  # Python 3.11+ stdlib
    import tomllib as tomli  # type: ignore[no-redef]


_DEFAULT_CONFIG_DIR = Path.home() / ".anvil"
_DEFAULT_CONFIG_PATH = _DEFAULT_CONFIG_DIR / "config.toml"


@dataclass
class Config:
    port: int = 4102
    host: str = "127.0.0.1"
    database_url: str = "postgresql+asyncpg://joneshong:dev_12345@localhost/workshop"
    skills_dir: Path = Path.home() / ".claude" / "skills"


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
        if "skills_dir" in raw:
            cfg.skills_dir = Path(os.path.expanduser(str(raw["skills_dir"])))

    # Env var overrides
    if v := os.environ.get("ANVIL_PORT"):
        cfg.port = int(v)
    if v := os.environ.get("ANVIL_HOST"):
        cfg.host = v
    if v := os.environ.get("ANVIL_DATABASE_URL"):
        cfg.database_url = v
    if v := os.environ.get("ANVIL_SKILLS_DIR"):
        cfg.skills_dir = Path(os.path.expanduser(v))

    return cfg


config = load_config()
