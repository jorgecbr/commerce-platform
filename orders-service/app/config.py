"""Runtime configuration, read once from the environment.

Flat on purpose. Nested settings models with per-model prefixes are a neat
trick that pydantic-settings only half supports, and a configuration layer
that silently falls back to defaults is worse than a flat one you can read in
a single screen. Every variable is validated at startup, so a typo fails
immediately instead of at three in the morning.
"""

from functools import lru_cache

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime configuration, read once from the environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    SERVICE_NAME: str = "orders-service"
    VERSION: str = "0.2.0"
    LOG_LEVEL: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    DEBUG: bool = False

    # --- PostgreSQL -------------------------------------------------------
    DATABASE_DSN: PostgresDsn | None = None
    DATABASE_POOL_SIZE: int = Field(default=10, gt=0)
    DATABASE_ECHO: bool = False

    # --- Redis ------------------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_TTL_SECONDS: int = Field(default=30, gt=0)

    # --- Kafka ------------------------------------------------------------
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:29092"
    KAFKA_ORDERS_TOPIC: str = "orders.events"
    KAFKA_INVENTORY_TOPIC: str = "inventory.events"
    KAFKA_CONSUMER_GROUP: str = "orders-service"

    @property
    def async_dsn(self) -> str:
        """Connection URL with the async driver selected.

        The DSN is written once, in its portable form, so the same value works
        for migrations, the test suite and the application.
        """
        if self.DATABASE_DSN is None:
            raise RuntimeError("DATABASE_DSN is not configured")
        return str(self.DATABASE_DSN).replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
