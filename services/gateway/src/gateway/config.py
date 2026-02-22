from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    port: int = 8800
    db_url: str = "postgresql://localhost/workshop"
    redis_url: str = "redis://localhost:6379/0"
    debug: bool = False

    model_config = {"env_prefix": "GATEWAY_"}


settings = Settings()
