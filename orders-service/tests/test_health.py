"""Smoke tests for the HTTP adapter.

The only tests in the suite that touch the network layer, and they still need
no Docker: the ASGI app is called in-process through ``httpx``.
"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

# The engine and the Redis client are both lazy: nothing connects until a
# request needs them, so these tests run without any infrastructure.
TEST_SETTINGS = Settings(
    DATABASE_DSN="postgresql://user:pass@localhost:5432/orders",
    REDIS_URL="redis://localhost:6379/15",
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Client over an app whose lifespan ran, so ``app.state`` is populated."""
    with TestClient(create_app(TEST_SETTINGS)) as value:
        yield value


def test_health_live_is_public(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "orders-service"


def test_readiness_reports_dependency_state(client: TestClient) -> None:
    """Readiness checks dependencies; liveness deliberately does not."""
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert "redis" in response.json()["checks"]


def test_unknown_route_returns_404(client: TestClient) -> None:
    assert client.get("/does-not-exist").status_code == 404


def test_unhandled_error_is_not_leaked_to_the_client() -> None:
    app: FastAPI = create_app(TEST_SETTINGS)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("connection string postgres://user:secret@db")

    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert response.status_code == 500
    # The internal message must not reach the client; it goes to the log.
    assert "secret" not in response.text
    assert response.json() == {
        "error": "InternalServerError",
        "detail": "internal server error",
    }
