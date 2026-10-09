"""Composition root.

The only module in the codebase allowed to know about every layer at once.
It reads the configuration, builds concrete adapters, wires them into the use
cases, and owns the process lifecycle.

    adapters/http ─┐
    adapters/db  ──┼──▶ application (use cases + ports) ──▶ domain
    adapters/cache ┘
"""

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.cache.redis_cache import RedisCache
from app.adapters.db.engine import create_engine, create_sessionmaker
from app.adapters.http import dependencies, health, orders
from app.config import Settings, get_settings
from app.domain import DomainError

logger = logging.getLogger(__name__)


class JsonFormatter(logging.Formatter):
    """One JSON object per line: greppable in a terminal, parsable by a collector."""

    def format(self, record: logging.LogRecord) -> str:
        """Render one log record as a single JSON object."""
        import json

        return json.dumps(
            {
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "module": record.module,
                "line": record.lineno,
            },
            default=str,
        )


def setup_logging(level: str) -> None:
    """Send structured logs to stdout, where the collector picks them up."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build and tear down the process-wide resources."""
    settings: Settings = app.state.settings
    engine: AsyncEngine = create_engine(
        dsn=settings.async_dsn,
        echo=settings.DATABASE_ECHO,
        pool_size=settings.DATABASE_POOL_SIZE,
    )
    sessionmaker = create_sessionmaker(engine)

    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    cache = RedisCache(redis_client, default_ttl_seconds=settings.CACHE_TTL_SECONDS)

    app.state.engine = engine
    app.state.cache = cache
    app.state.settings = settings
    dependencies.configure(sessionmaker, cache)

    logger.info("%s %s started", settings.SERVICE_NAME, settings.VERSION)
    try:
        yield
    finally:
        await cache.close()
        await engine.dispose()
        logger.info("%s stopped", settings.SERVICE_NAME)


def register_error_handlers(app: FastAPI) -> None:
    """Map domain errors to HTTP status codes.

    Every ``DomainError`` is a business outcome the caller can act on, so it
    becomes a 4xx with a machine-readable code. Anything else is a bug and
    becomes an opaque 500: the traceback is logged, the message is not shared.
    """

    @app.exception_handler(DomainError)
    async def handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": type(exc).__name__, "detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "InternalServerError", "detail": "internal server error"},
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Assemble the application."""
    settings = settings or get_settings()
    setup_logging(settings.LOG_LEVEL)

    app = FastAPI(
        title="Orders Service",
        summary="Order management for the commerce platform",
        version=settings.VERSION,
        lifespan=lifespan,
        docs_url="/docs" if settings.DEBUG else None,
    )
    app.state.settings = settings

    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(orders.router)
    return app
