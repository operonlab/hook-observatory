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

    # --- Sysmon Collector ---
    SYSMON_COLLECT_INTERVAL: int = 5
    SYSMON_DISK_CACHE_TTL: int = 60
    SYSMON_OUTPUT_PATH: str = "/tmp/agent-metrics-sysmon.json"
    SYSMON_COMPAT_PATH: str = "/tmp/pulso-sysmon-latest.json"
    SYSMON_HISTORY_SIZE: int = 720  # 1h @ 5s

    # --- LLM Quota Collector ---
    QUOTA_CACHE_TTL: int = 60
    QUOTA_COMPAT_PATH: str = "/tmp/pulso-quota-all.json"
    CODEX_AUTH_PATH: str = "~/.codex/auth.json"
    GM_OAUTH_PATH: str = "~/.gemini/oauth_creds.json"
    GM_CLIENT_ID: str = "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
    GM_CLIENT_SECRET: str = "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"

    # --- Guardian ---
    GUARDIAN_WARN_THRESHOLD: int = 40
    GUARDIAN_CRIT_THRESHOLD: int = 8
    GUARDIAN_IDLE_CPU: float = 1.0
    GUARDIAN_MIN_AGE: int = 600
    GUARDIAN_GRACE_SECONDS: int = 60
    GUARDIAN_COOLDOWN: int = 120
    GUARDIAN_SUSTAINED_CHECKS: int = 3
    EXPENDABLE_APPS: list[str] = [
        "Google Chrome Helper (Renderer)|Chrome Tabs",
        "LINE|LINE",
        "LineCall|LINE Call",
        "openclaw-gateway|OpenClaw",
        "AltServer|AltServer",
    ]

    # --- Process Sweep ---
    SWEEP_INTERVAL: int = 1800  # 30 minutes
    MCP_CONFIG_PATHS: list[str] = [
        "~/.mcp.json",
        "~/workshop/.mcp.json",
    ]
    MCP_EXTRA_PATTERNS: list[str] = []
    SWEEP_CPU_THRESHOLD: float = 80.0
    SWEEP_CPU_MIN_AGE: int = 600
    SWEEP_CPU_WHITELIST: list[str] = ["claude", "ollama"]
    SWEEP_STALE_WARN_HOURS: int = 24
    SWEEP_STALE_KILL_HOURS: int = 48
    SWEEP_STALE_WHITELIST: list[str] = ["claude", "cost-server", "browser-tools-server"]

    model_config = {"env_prefix": "AGENT_METRICS_", "env_file": ".env", "extra": "ignore"}

    @property
    def expendable_list(self) -> list[tuple[str, str]]:
        result = []
        for entry in self.EXPENDABLE_APPS:
            if "|" in entry:
                pattern, name = entry.split("|", 1)
                result.append((pattern, name))
        return result

    @property
    def mcp_pattern_list(self) -> list[str]:
        return self.MCP_EXTRA_PATTERNS


settings = Settings()
