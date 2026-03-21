"""Video Edit configuration — pydantic-settings with VIDEO_EDIT_* env prefix."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

STATION_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    SERVICE_NAME: str = "video-edit"
    PORT: int = 4110
    HOST: str = "127.0.0.1"
    DEBUG: bool = False

    # Project storage
    PROJECTS_DIR: str = str(Path.home() / "workshop" / "outputs" / "video-edit" / "projects")

    # Preview output
    PREVIEW_DIR: str = str(Path.home() / "workshop" / "outputs" / "video-edit" / "previews")

    # melt binary path
    MELT_BIN: str = "melt"

    # Default video settings
    DEFAULT_WIDTH: int = 1920
    DEFAULT_HEIGHT: int = 1080
    DEFAULT_FPS_NUM: int = 30
    DEFAULT_FPS_DEN: int = 1

    model_config = {"env_prefix": "VIDEO_EDIT_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
