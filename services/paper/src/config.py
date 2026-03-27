"""Paper Service configuration — loaded from environment variables (PAPER_ prefix)."""

from pydantic_settings import BaseSettings


class PaperSettings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = 10010
    debug: bool = False

    # Database
    db_url: str = ""  # Set via PAPER_DB_URL env var

    # Redis (optional — cache degrades gracefully when unavailable)
    redis_url: str = "redis://localhost:6379/0"

    # Internal auth (X-Internal-Key header for SDK/CLI/MCP calls)
    # In microservice mode, used to trust callers without full session auth
    internal_api_key: str = ""

    # Auth bypass for dev — set PAPER_AUTH_BYPASS=1 to skip permission checks
    auth_bypass: bool = False
    # Default user role when auth_bypass=True
    bypass_role: str = "admin"

    # CORS
    cors_origins: list[str] = [
        "http://localhost:10500",
        "https://workshop.joneshong.com",
    ]

    # LLM / digest generation
    litellm_base_url: str = "http://localhost:4000/v1"
    litellm_api_key: str = "sk-litellm-local-dev"
    haiku_model: str = "claude-haiku-4-5"

    model_config = {"env_prefix": "PAPER_"}


settings = PaperSettings()
