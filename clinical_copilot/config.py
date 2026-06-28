"""Configuration management for ClinicalCopilot."""

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class ClinicalInsightConfig(BaseModel):
    """Configuration for Clinical Insight API."""
    base_url: str = "http://localhost:8001"
    timeout: int = 30


class ClinicalReasoningConfig(BaseModel):
    """Configuration for Clinical Reasoning Trainer."""
    base_url: str = "https://clinical-reasoning-trainer-one.vercel.app"
    timeout: int = 30


class OllamaConfig(BaseModel):
    """Configuration for local Ollama LLM."""
    base_url: str = "http://localhost:11434"
    primary_model: str = "llama3:latest"
    fallback_model: str = "phi3:mini"
    timeout: int = 120


class ScreenpipeConfig(BaseModel):
    """Configuration for Screenpipe integration."""
    base_url: str = "http://localhost:3030"
    poll_interval: float = 1.0  # seconds (was 3.0)
    timeout: int = 10


class PrivacyConfig(BaseModel):
    """Privacy filter configuration."""
    excluded_apps: list[str] = [
        "Safari",
        "Mail",
        "Messages",
        "FaceTime",
        "1Password",
        "Bitwarden",
        "Chase",
        "Wells Fargo",
        "Bank of America",
        "Facebook",
        "Twitter",
        "Instagram",
        "TikTok",
        "Gmail",
        "Yahoo Mail",
    ]
    clinical_only_mode: bool = False


class MemoryConfig(BaseModel):
    """Memory system configuration."""
    db_path: Path = Path.home() / ".clinical-copilot" / "memory.db"
    max_working_memory: int = 10
    short_term_hours: int = 24
    consolidation_threshold: float = 0.7


class Settings(BaseSettings):
    """Main application settings."""

    # Mode settings
    specialty_mode: str = "general"  # general, wound-care, learning

    # Component configs
    clinical_insight: ClinicalInsightConfig = ClinicalInsightConfig()
    clinical_reasoning: ClinicalReasoningConfig = ClinicalReasoningConfig()
    ollama: OllamaConfig = OllamaConfig()
    screenpipe: ScreenpipeConfig = ScreenpipeConfig()
    privacy: PrivacyConfig = PrivacyConfig()
    memory: MemoryConfig = MemoryConfig()

    # Paths
    data_dir: Path = Path.home() / ".clinical-copilot"
    log_file: Optional[Path] = None

    # Alert settings
    alert_cooldown: int = 30  # seconds between similar alerts
    min_confidence: float = 0.6  # minimum confidence to show alert

    class Config:
        env_prefix = "COPILOT_"
        env_file = ".env"

    def ensure_dirs(self) -> None:
        """Ensure required directories exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.memory.db_path.parent.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
