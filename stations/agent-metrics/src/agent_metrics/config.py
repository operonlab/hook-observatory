"""Agent Metrics configuration — pydantic-settings with AGENT_METRICS_* env prefix."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

STATION_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    SERVICE_NAME: str = "agent-metrics"
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

    # Session tracking
    SESSION_EXPIRY_SECONDS: int = 7200
    DB_FLUSH_INTERVAL: int = 60
    EXPIRY_CHECK_INTERVAL: int = 10
    RETENTION_SNAPSHOTS_DAYS: int = 30
    RETENTION_DAILY_DAYS: int = 365
    FALLBACK_PATH: str = "/tmp/agent-metrics-latest.json"

    # --- LLM Usage (merged from llm-usage station) ---

    SUBSCRIPTIONS: dict = {
        "claude-code": {
            "provider": "anthropic",
            "plan": "max_5",
            "monthly_cost_usd": 100.00,
        },
        "codex-cli": {
            "provider": "openai",
            "plan": "pro",
            "monthly_cost_usd": 200.00,
        },
        "gemini-cli": {
            "provider": "google",
            "plan": "advanced",
            "monthly_cost_usd": 0,
        },
    }
    API_MONTHLY_BUDGET_USD: float = 50.0
    BUDGET_WARNING_PCT: float = 80.0
    SYSMON_URL: str = "http://localhost:8800/api/sysmon/current"
    MODEL_POLICY_STATE_PATH: str = "~/.claude/data/model-policy/state.json"
    MODEL_POLICY_CONFIG_PATH: str = "~/.claude/data/model-policy/config.json"
    CCUSAGE_BIN: str = "/opt/homebrew/bin/ccusage"
    COLLECTION_INTERVAL_SECONDS: int = 1800
    COLLECTION_SNAPSHOT_DIR: str = "~/.claude/data/llm-usage/snapshots"
    COLLECTION_LATEST_FILE: str = "~/.claude/data/llm-usage/latest.json"
    COLLECTION_RETENTION_DAYS: int = 90

    # Redis (for push notifications)
    REDIS_URL: str = "redis://localhost:6379/0"

    model_config = {"env_prefix": "AGENT_METRICS_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
