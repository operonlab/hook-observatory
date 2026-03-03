"""AgentOps configuration — pydantic-settings with AGENTOPS_* env prefix."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

STATION_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    SERVICE_NAME: str = "agentops"
    PORT: int = 8795
    HOST: str = "127.0.0.1"
    DEBUG: bool = False

    # PostgreSQL (workshop shared instance)
    DATABASE_URL: str = "postgresql://joneshong:dev_12345@localhost:5432/workshop"

    # Routing table (YAML)
    ROUTING_TABLE_PATH: str = str(STATION_DIR / "config" / "routing_table.yaml")

    # Headless CLI paths
    SKILLS_DIR: str = str(Path.home() / ".claude" / "skills")

    # Agent defaults
    DEFAULT_TIMEOUT: int = 300
    DEFAULT_BUDGET: str = "balanced"

    # Hook Observatory (fire-and-forget notifications)
    HOOK_URL: str = "http://127.0.0.1:4100/api/hooks"

    model_config = {"env_prefix": "AGENTOPS_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
