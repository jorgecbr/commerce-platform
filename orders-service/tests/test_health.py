"""Smoke tests for the HTTP adapter.

The only tests in the suite that touch the network layer, and they still need
no Docker: the ASGI app is called in-process through ``httpx``.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health_live_is_public(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "orders-service", "version": "0.1.0"}


def test_unknown_route_returns_404(client: TestClient) -> None:
    assert client.get("/does-not-exist").status_code == 404


def test_unhandled_error_is_not_leaked_to_the_client() -> None:
    app: FastAPI = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("connection string postgres://user:secret@db")

    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert response.status_code == 500
    # The internal message must not reach the client; it goes to the log.
    assert "secret" not in response.text
    assert response.json() == {"detail": "internal server error"}
