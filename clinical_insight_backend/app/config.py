from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    app_name: str = "Clinical Insight Engine"
    debug: bool = True

    # LLM Configuration
    llm_provider: str = "anthropic"  # "anthropic" or "openai"
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    model_name: str = "claude-sonnet-4-20250514"

    class Config:
        env_file = ".env"


settings = Settings()
