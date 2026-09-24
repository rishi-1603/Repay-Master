"""RepayMaster API configuration.

Day 2: auth/history settings added alongside those endpoints (loan/risk
calculation needed none of this on Day 1).
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

    # JWT for /history: a REST API has no server-side session to lean on, so
    # a short-lived signed bearer token issued at /auth/login is how
    # subsequent requests prove who they are without re-hitting sqlite with
    # a password on every call. This default is fine for local development
    # only -- it is intentionally NOT a secure production value, and is
    # flagged as such in .env.example and the README (same known gap as
    # DevTrack's SECRET_KEY, tracked honestly rather than silently shipped).
    SECRET_KEY: str = "dev-only-insecure-secret-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

