from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "AUTO_SURVEY_"}

    database_url: str = "postgresql://joneshong:dev_12345@localhost/workshop"
    schema_name: str = "auto_survey"

    llm_backend: str = "gemini"  # gemini | claude | codex
    llm_model: str = ""  # empty = CLI default

    min_delay: int = 5
    max_delay: int = 15
    headless: bool = True

    playwright_cli: str = "npx @playwright/cli"
    pw_profile_dir: str = ""  # empty = use temp APFS clone

    execution_hour: int = 14  # execute after this hour; before → scheduled

    web_port: int = 4102
    bark_device_key: str = "gx7KnK5f8iAKuqNLWzy5hP"
    bark_server: str = "http://localhost:8090"


settings = Settings()
