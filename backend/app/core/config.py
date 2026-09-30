"""RepayMaster API configuration.

Day 2: auth/history settings added alongside those endpoints (loan/risk
calculation needed none of this on Day 1).
"""
import warnings
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# HS256 signs with the secret as a raw HMAC key. RFC 7518 section 3.2 requires
# the key to be at least as long as the hash output -- 32 bytes for SHA-256 --
# and PyJWT warns below that. A short key is not a style problem: it makes the
# signature brute-forceable offline from any single captured token.
MIN_SECRET_KEY_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "RepayMaster API"
    APP_ENV: str = "development"
    DEBUG: bool = True

    # CORS: the Streamlit client and any future frontend need to call this API
    # cross-origin during local development.
    #
    # The wildcard default survives for development convenience ONLY, and it is
    # no longer able to do damage: app/core/cors.py refuses a wildcard when
    # APP_ENV=production (loud startup failure) and never pairs a wildcard with
    # allow_credentials in any environment. A production deployment must set
    # this to the exact origins it serves. See finding S7 in the audit.
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

    @model_validator(mode="after")
    def _secret_key_must_be_long_enough(self) -> "Settings":
        """Refuse to run in production with a signing key short enough to
        brute-force (finding S15).

        Requiring the field (above) stops a *missing* secret; this stops a *weak*
        one, which is the failure mode that survives a deployment checklist
        because everything appears to work. Below the minimum it is a hard
        failure when APP_ENV=production and a loud warning otherwise -- the same
        asymmetry as app/core/cors.py, and for the same reason: a rule that fails
        unconditionally could take a running service down over a development key,
        which trades a real control for an outage. Production is where the key
        protects real tokens, so production is where it is enforced.

        Note this project hashes passwords with PBKDF2 rather than relying on a
        JWT library's defaults, but the *token signing* key is exactly as
        sensitive: whoever holds it can mint a valid token for any user without
        touching the password store at all.
        """
        length = len(self.SECRET_KEY.encode("utf-8"))
        if length >= MIN_SECRET_KEY_BYTES:
            return self

        message = (
            f"SECRET_KEY is {length} bytes; at least {MIN_SECRET_KEY_BYTES} are required, "
            "because HS256 uses it directly as an HMAC key (RFC 7518 3.2) and a shorter key "
            "can be brute-forced offline from any single captured token. Generate one with: "
            'python -c "import secrets; print(secrets.token_hex(32))"'
        )
        if self.APP_ENV.strip().lower() == "production":
            raise ValueError(f"Refusing to start in production: {message}")
        warnings.warn(f"Non-production only, and not acceptable in production: {message}", stacklevel=2)
        return self

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

