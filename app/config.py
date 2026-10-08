"""Centralized application settings, read exclusively from environment variables."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration sourced from environment variables / .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg2://helpdesk:helpdesk@localhost:5432/helpdesk"
    REDIS_URL: str = "redis://localhost:6379/0"
    JWT_SECRET: str = "change-me-in-production"
    ADMIN_EMAIL: str | None = None
    ADMIN_PASSWORD: str | None = None
    CORS_ORIGINS: str = "*"
    PORT: int = 8000

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 10

    @property
    def cors_origins_list(self) -> list[str]:
        raw = (self.CORS_ORIGINS or "*").strip()
        if raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (environment is read once per process)."""
    return Settings()


settings = get_settings()
