"""Composition root.

The only module in the codebase allowed to know about every layer at once.
It reads the configuration, builds concrete adapters, and injects them into
the use cases. Adding a technology means editing this file and nowhere else -
that is the whole point of the dependency rule.

    adapters/http ─┐
    adapters/db  ──┼──▶ application (use cases + ports) ──▶ domain
                   ┘            ▲
                                │ imports only Protocols
"""

import logging
import sys

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.adapters.http import health
from app.config import get_settings

logger = logging.getLogger(__name__)


class JsonFormatter(logging.Formatter):
    """One JSON object per line: greppable in the terminal, parsable by Loki."""

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


def create_app() -> FastAPI:
    """Assemble the application: settings, logging, routers, error handlers."""
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)

    app = FastAPI(
        title="Orders Service",
        summary="Order management for the commerce platform",
        version=settings.VERSION,
        docs_url="/docs" if settings.DEBUG else None,
    )

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        """Never leak an internal message to the client; log it with the stack."""
        logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "internal server error"},
        )

    app.include_router(health.router)
    logger.info("%s %s started", settings.SERVICE_NAME, settings.VERSION)
    return app


app = create_app()
