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

    def validate_secret_key(self) -> None:
        """Raise if secret_key is the insecure default."""
        if self.secret_key == "change-me-in-production":
            raise ValueError(
                "CORE_SECRET_KEY is set to the default value. "
                "Set a secure random secret via CORE_SECRET_KEY environment variable."
            )

    # CORS
    cors_origins: list[str] = [
        "http://localhost:3000",
        "https://claw.joneshong.com",
    ]

    # Session
    session_cookie_name: str = "workshop_session"
    session_max_age: int = 7 * 24 * 60 * 60  # 7 days in seconds

    # OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    oauth_redirect_base: str = "http://localhost:8800"

    # Auth seed
    admin_email: str = ""
    admin_password: str = ""

    # Event Bus
    event_backend: str = "memory"  # "memory" | "redis"

    # Plugins
    plugin_dir: str = "plugins"

    model_config = {"env_prefix": "CORE_"}


settings = Settings()
