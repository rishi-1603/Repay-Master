from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "RepayMaster AI"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "supersecretkey_please_change_in_production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/repaymaster"
    GEMINI_API_KEY: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
