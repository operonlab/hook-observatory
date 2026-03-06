from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "AUTO_SURVEY_"}

    database_url: str = "postgresql://joneshong:dev_12345@localhost/workshop"
    schema_name: str = "auto_survey"

    llm_backend: str = "gemini"  # gemini | claude | codex
    llm_model: str = ""  # empty = CLI default

    min_delay: int = 30
    max_delay: int = 180
    headless: bool = True

    playwright_cli: str = "npx @playwright/cli"
    pw_profile_dir: str = ""  # empty = use temp APFS clone


settings = Settings()
