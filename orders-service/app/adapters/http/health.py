"""Health endpoints.

Two separate probes, because they answer different questions:

* ``/health/live``  - "is the process alive?" Kubernetes restarts the pod if
  this fails. It must never check dependencies: a database outage would then
  restart every pod and turn a degradation into an outage.
* ``/health/ready`` - "can this pod serve traffic?" It does check
  dependencies, so the load balancer stops sending requests here while a
  dependency is unreachable.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from app.adapters.cache.redis_cache import RedisCache
from app.adapters.http.dependencies import get_cache

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Body returned by the liveness probe."""

    status: str
    service: str
    version: str


class ReadinessResponse(HealthResponse):
    """Readiness adds the state of each dependency."""

    checks: dict[str, str]


@router.get("/health/live", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def live(request: Request) -> HealthResponse:
    """Report that the process is running.

    Deliberately does not touch a database: if liveness depended on it, a
    dependency outage would make the orchestrator restart every pod and turn a
    degradation into a full outage.
    """
    settings = request.app.state.settings
    return HealthResponse(status="ok", service=settings.SERVICE_NAME, version=settings.VERSION)


@router.get("/health/ready", response_model=ReadinessResponse, status_code=status.HTTP_200_OK)
async def ready(
    request: Request,
    cache: Annotated[RedisCache, Depends(get_cache)],
) -> ReadinessResponse:
    """Report whether this pod can serve traffic right now.

    Checks the cache here. The database check lands with the outbox relay,
    which is the component that actually needs it to make progress.
    """
    settings = request.app.state.settings
    redis_ok = await cache.ping()
    return ReadinessResponse(
        status="ok" if redis_ok else "degraded",
        service=settings.SERVICE_NAME,
        version=settings.VERSION,
        checks={"redis": "ok" if redis_ok else "unreachable"},
    )
