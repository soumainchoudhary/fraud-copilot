"""Application configuration via pydantic-settings.

Loads settings from environment variables and .env file.
No hardcoded keys or paths — everything is configurable.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Model ---
    model_path: str = "models/xgboost_fraud_v1.joblib"
    model_version: str = "xgboost-v1"
    flag_threshold: float = 0.5

    # --- Gemini API ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"

    # --- ChromaDB ---
    chroma_persist_dir: str = "data/chroma_db"

    # --- Database & Redis ---
    database_url: str = "sqlite:///data/fraud_copilot.db"
    redis_url: str = ""

    # --- Security & Auth ---
    api_key: str = ""  # If set, enables API Key enforcement on /score, /ask, /cases
    allowed_origins: str = "http://localhost:8000,http://127.0.0.1:8000"
    rate_limit_per_minute: int = 120
    ask_rate_limit_per_minute: int = 30
    enable_security_headers: bool = True
    max_query_length: int = 1000

    # --- Logging ---
    log_level: str = "INFO"

    @property
    def cors_origins(self) -> List[str]:
        """Parse allowed origins from comma-separated string."""
        if not self.allowed_origins:
            return ["http://localhost:8000", "http://127.0.0.1:8000"]
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings singleton."""
    return Settings()
