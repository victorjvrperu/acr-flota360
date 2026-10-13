from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "ACR Flota360"
    APP_ENV: str = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    DATABASE_URL: str = "sqlite:///./acr_flota360.db"
    SECRET_KEY: str = "acr_flota360_secret_key"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    GEMINI_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
