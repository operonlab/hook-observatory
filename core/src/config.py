"""Core configuration — loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = 8800
    debug: bool = False

    # Database & Cache
    db_url: str = "postgresql://joneshong:dev_12345@localhost/workshop"
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
    session_max_age: int = 30 * 24 * 60 * 60  # 30 days in seconds

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

    # S3 Object Storage (RustFS)
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "rustfsadmin"
    s3_secret_key: str = "rustfsadmin"
    s3_archive_bucket: str = "workshop-archive"

    # Web Push (VAPID)
    vapid_private_key: str = ""  # path to PEM file or inline PEM
    vapid_public_key: str = ""  # base64url-encoded applicationServerKey
    vapid_contact: str = "mailto:admin@joneshong.com"

    # Bark (iPhone push via self-hosted Bark server)
    bark_server_url: str = ""  # e.g. http://localhost:8090
    bark_device_key: str = ""  # device key from Bark iOS app

    # Plugins
    plugin_dir: str = "plugins"

    model_config = {"env_prefix": "CORE_"}


settings = Settings()
