"""Health endpoints.

Two separate probes, because they answer different questions:

* ``/health/live``  - "is the process alive?" Kubernetes restarts the pod if
  this fails. It must never check dependencies: a database outage would then
  restart every pod and turn a degradation into an outage.
* ``/health/ready`` - "can this pod serve traffic?" It does check
  dependencies, so the load balancer stops sending requests here while the
  database is unreachable. Added in the next milestone, once there is a
  database to check.
"""

from fastapi import APIRouter, status
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Body returned by the liveness probe."""

    status: str
    service: str
    version: str


@router.get("/health/live", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def live() -> HealthResponse:
    """Report that the process is running.

    Deliberately does not touch the database: if liveness depended on it, a
    database outage would make Kubernetes restart every pod and turn a
    degradation into a full outage.
    """
    return HealthResponse(status="ok", service="orders-service", version="0.1.0")
