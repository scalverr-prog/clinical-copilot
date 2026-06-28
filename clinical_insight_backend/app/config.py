from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    app_name: str = "Clinical Insight Engine"
    debug: bool = True

    # LLM Configuration - defaults to local Ollama
    llm_provider: str = "ollama"  # "ollama" (local), "anthropic", or "openai"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mistral:7b"  # Faster on Intel Mac, good clinical reasoning

    # Optional cloud APIs (only if llm_provider is set to use them)
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    model_name: str = "llama3:latest"  # Used for cloud providers

    class Config:
        env_file = ".env"


settings = Settings()
