# syntax=docker/dockerfile:1
#
# Multi-stage build. The final image carries no compiler and no test
# dependencies, which keeps it small and removes a whole class of supply chain
# risk from whatever ends up in production.

# ---------------------------------------------------------------------------
# Builder: install dependencies into a self-contained virtualenv
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /code

# Dependencies change far less often than the code, so they are resolved in
# their own layer. A code change does not re-download the whole dependency tree.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/code/.venv/bin:$PATH"

# curl is only here for the container healthcheck below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# An unprivileged user: a container process that does not need root should not
# have it, even inside the container.
RUN useradd --create-home --uid 10001 appuser

WORKDIR /code
COPY --from=builder --chown=appuser:appuser /code /code

USER appuser

EXPOSE 8000

# Liveness only: readiness is a separate route so the orchestrator can tell
# "process is up" from "process can serve traffic".
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health/live || exit 1

# Factory pattern: importing the module must not configure logging as a side
# effect, so the app is built by uvicorn on startup.
CMD ["uvicorn", "app.main:create_app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8000"]