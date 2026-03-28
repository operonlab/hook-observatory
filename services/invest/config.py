"""Invest Service configuration — pydantic-settings with INVEST_ prefix."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DB_URL: str = "postgresql+asyncpg://localhost/workshop"
    DB_SCHEMA: str = "invest"
    HOST: str = "127.0.0.1"
    PORT: int = 10012
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_prefix="INVEST_")


settings = Settings()
