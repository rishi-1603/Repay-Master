"""RepayMaster API configuration.

Kept deliberately small on Day 1: only what /loan/calculate and /risk/predict
need. Auth/history settings are added on Day 2 alongside those endpoints.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "RepayMaster API"
    APP_ENV: str = "development"
    DEBUG: bool = True

    # CORS: the Streamlit client and any future frontend need to call this API
    # cross-origin during local development.
    CORS_ORIGINS: str = "*"

    GEMINI_API_KEY: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
