"""Intelflow Service configuration — pydantic-settings with INTELFLOW_ prefix."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DB_URL: str = "postgresql+asyncpg://localhost/workshop"
    DB_SCHEMA: str = "intelflow"
    HOST: str = "127.0.0.1"
    PORT: int = 10011
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_prefix="INTELFLOW_")


settings = Settings()
