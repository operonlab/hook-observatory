from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "AUTO_SURVEY_"}

    database_url: str = "postgresql://joneshong:dev_12345@localhost/workshop"
    schema_name: str = "auto_survey"

    llm_backend: str = "litellm"  # litellm | gemini | claude | codex
    llm_model: str = "grok-4-fast"  # litellm model name
    litellm_base_url: str = "http://localhost:4000/v1"
    litellm_api_key: str = "sk-litellm-local-dev"

    min_delay: int = 5
    max_delay: int = 15
    headless: bool = True

    playwright_cli: str = "npx @playwright/cli"
    pw_profile_dir: str = ""  # empty = use temp APFS clone

    execution_hour: int = 14  # execute after this hour; before → scheduled

    web_port: int = 4102
    bark_device_key: str = "gx7KnK5f8iAKuqNLWzy5hP"
    bark_server: str = "http://localhost:8090"

    line_community_name: str = "微光早餐會"
    line_enabled: bool = True
    line_scroll_pages: int = 3  # Page Up attempts to find older messages


settings = Settings()
