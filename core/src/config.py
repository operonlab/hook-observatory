"""Core configuration — loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = 8800
    debug: bool = False

    # Database & Cache
    db_url: str = "postgresql://localhost/workshop"
    redis_url: str = "redis://localhost:6379/0"

    # Security
    secret_key: str = "change-me-in-production"

    # CORS
    cors_origins: list[str] = [
        "http://localhost:3000",
        "https://claw.joneshong.com",
    ]

    # Session
    session_cookie_name: str = "workshop_session"
    session_max_age: int = 7 * 24 * 60 * 60  # 7 days in seconds

    # Event Bus
    event_backend: str = "memory"  # "memory" | "redis"

    # Plugins
    plugin_dir: str = "plugins"

    model_config = {"env_prefix": "CORE_"}


settings = Settings()
