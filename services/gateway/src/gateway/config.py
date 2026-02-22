"""Gateway configuration — loaded from environment variables."""

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
    session_cookie_name: str = "gw_session"
    session_max_age: int = 7 * 24 * 60 * 60  # 7 days in seconds

    # Downstream service registry: name -> base_url
    service_registry: dict[str, str] = {
        "finance": "http://127.0.0.1:8810",
        "quest": "http://127.0.0.1:8811",
        "muse": "http://127.0.0.1:8812",
    }

    model_config = {"env_prefix": "GATEWAY_"}


settings = Settings()
