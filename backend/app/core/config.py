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
    # a password on every call.
    #
    # No default on purpose (Day 3 fix, applied here for the same reason it
    # was applied to the sibling DevTrack project the same day): a
    # hardcoded fallback secret would silently sign real JWTs with a
    # well-known string in any environment where SECRET_KEY was forgotten,
    # including production. Missing SECRET_KEY is now a loud startup
    # failure instead. See backend/app/tests/conftest.py for how tests
    # supply one, and .env.example / docker-compose.yml for how a real
    # deployment must.
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Brute-force mitigation on POST /auth/login (Day 4). Two independent
    # limits, because each alone is trivially evaded:
    #   - per-IP bounds one source hammering many usernames (credential
    #     stuffing), which a per-account limit would never see.
    #   - per-account bounds many distributed sources guessing one
    #     username, which a per-IP limit would never see.
    # The per-IP limit counts EVERY attempt and is generous; the per-account
    # limit counts only FAILED attempts and is tight, and resets on success --
    # so a legitimate user who mistypes once and then succeeds is not
    # penalised, while an attacker guessing at one account is stopped after
    # a handful of tries. See app/core/rate_limit.py for why these are
    # in-process rather than Redis-backed in this project specifically.
    LOGIN_IP_LIMIT: int = 20
    LOGIN_IP_WINDOW_SECONDS: int = 60
    LOGIN_ACCOUNT_FAILURE_LIMIT: int = 5
    LOGIN_ACCOUNT_WINDOW_SECONDS: int = 300



@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

