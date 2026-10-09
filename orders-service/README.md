# orders-service

Order management for the commerce platform. Python 3.12 + FastAPI, built with
Domain-Driven Design and Clean Architecture.

> The full architecture, the roadmap and the study material live in the
> [repository README](../README.md).

## Layering

```
app/
├── domain/         # entities, value objects, invariants. Zero dependencies.
├── application/    # use cases + ports (Protocols). Depends only on domain.
└── adapters/       # http, db, cache, events. Implements the ports.
```

The dependency rule points inwards: `adapters → application → domain`. The
domain imports nothing from the rest of the codebase.

## Run it

```shell
uv sync
uv run uvicorn app.main:app --reload
```

## Test it

```shell
uv run pytest              # whole suite, no Docker needed
uv run pytest --cov=app    # with coverage
```

`uv run ruff check .` · `uv run ruff format --check .` · `uv run mypy`