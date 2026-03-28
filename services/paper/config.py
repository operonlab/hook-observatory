"""Paper Service configuration — pydantic-settings with PAPER_ prefix."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DB_URL: str = "postgresql+asyncpg://localhost/workshop"
    DB_SCHEMA: str = "paper"
    HOST: str = "127.0.0.1"
    PORT: int = 10010
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_prefix="PAPER_")


settings = Settings()
