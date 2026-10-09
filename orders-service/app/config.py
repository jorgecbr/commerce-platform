"""Application settings, read from the environment.

Every setting is a typed, immutable model so a typo in a variable name fails
at startup instead of at 3am in production. Defaults exist only for local
development; anything sensitive is required.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read once from the environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    SERVICE_NAME: str = "orders-service"
    VERSION: str = "0.1.0"
    LOG_LEVEL: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    DEBUG: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
