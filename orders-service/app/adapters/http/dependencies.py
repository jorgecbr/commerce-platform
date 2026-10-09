"""Dependency wiring for the HTTP layer.

FastAPI resolves everything through these functions. Keeping them here means
the routers stay free of construction logic, and swapping an adapter (for a
test, or for another implementation) is a one-line change in one file.

This module is part of the composition root: it is allowed to know about the
concrete adapters and the use cases at the same time.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.cache.redis_cache import RedisCache
from app.adapters.db.repositories import (
    SqlAlchemyOrderRepository,
    SqlAlchemyOutboxPublisher,
    SqlAlchemyUnitOfWork,
    SystemClock,
    UuidGenerator,
)
from app.application.commands.change_order_status import CancelOrder, ConfirmOrder
from app.application.commands.place_order import PlaceOrder
from app.application.queries.get_order import GetOrder
from app.domain import PricingService

# Process-wide singletons. Created once in the lifespan hook and read from
# every request, so the engine and the Redis pool are not rebuilt per call.
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_redis: RedisCache | None = None


def configure(smaker: async_sessionmaker[AsyncSession], redis: RedisCache) -> None:
    """Wire the process-wide singletons. Called once from the lifespan hook."""
    global _sessionmaker, _redis  # deliberate process-level wiring
    _sessionmaker = smaker
    _redis = redis


async def get_session() -> AsyncIterator[AsyncSession]:
    """Provide a session scoped to the request.

    The session is rolled back on error and closed on the way out. Committing
    is the unit of work's job, never the framework's, because the outbox entry
    and the state change have to land together.
    """
    if _sessionmaker is None:  # pragma: no cover - a wiring bug, not a runtime path
        raise RuntimeError("dependencies.configure() was never called")
    async with _sessionmaker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_clock() -> SystemClock:
    """Provide the system clock."""
    return SystemClock()


def get_ids() -> UuidGenerator:
    """Provide the order identifier generator."""
    return UuidGenerator()


def get_pricing() -> PricingService:
    """Provide the stateless pricing service."""
    return PricingService()


def get_orders(session: SessionDep) -> SqlAlchemyOrderRepository:
    """Provide the order repository bound to the request session."""
    return SqlAlchemyOrderRepository(session)


def get_publisher(session: SessionDep) -> SqlAlchemyOutboxPublisher:
    """Provide the outbox publisher bound to the request session."""
    return SqlAlchemyOutboxPublisher(session)


def get_unit_of_work(session: SessionDep) -> SqlAlchemyUnitOfWork:
    """Provide the unit of work bound to the request session."""
    return SqlAlchemyUnitOfWork(session)


def get_cache(request: Request) -> RedisCache:
    """Provide the process-wide Redis cache."""
    cache: RedisCache = request.app.state.cache
    return cache


def get_place_order(
    orders: Annotated[SqlAlchemyOrderRepository, Depends(get_orders)],
    publisher: Annotated[SqlAlchemyOutboxPublisher, Depends(get_publisher)],
    unit_of_work: Annotated[SqlAlchemyUnitOfWork, Depends(get_unit_of_work)],
    clock: Annotated[SystemClock, Depends(get_clock)],
    ids: Annotated[UuidGenerator, Depends(get_ids)],
    pricing: Annotated[PricingService, Depends(get_pricing)],
) -> PlaceOrder:
    """Assemble the PlaceOrder use case."""
    return PlaceOrder(
        orders=orders,
        publisher=publisher,
        clock=clock,
        ids=ids,
        transactions=unit_of_work,
        pricing=pricing,
    )


def get_confirm_order(
    orders: Annotated[SqlAlchemyOrderRepository, Depends(get_orders)],
    publisher: Annotated[SqlAlchemyOutboxPublisher, Depends(get_publisher)],
    unit_of_work: Annotated[SqlAlchemyUnitOfWork, Depends(get_unit_of_work)],
    clock: Annotated[SystemClock, Depends(get_clock)],
) -> ConfirmOrder:
    """Assemble the ConfirmOrder use case."""
    return ConfirmOrder(orders=orders, publisher=publisher, clock=clock, transactions=unit_of_work)


def get_cancel_order(
    orders: Annotated[SqlAlchemyOrderRepository, Depends(get_orders)],
    publisher: Annotated[SqlAlchemyOutboxPublisher, Depends(get_publisher)],
    unit_of_work: Annotated[SqlAlchemyUnitOfWork, Depends(get_unit_of_work)],
    clock: Annotated[SystemClock, Depends(get_clock)],
) -> CancelOrder:
    """Assemble the CancelOrder use case."""
    return CancelOrder(orders=orders, publisher=publisher, clock=clock, transactions=unit_of_work)


def get_get_order(
    orders: Annotated[SqlAlchemyOrderRepository, Depends(get_orders)],
) -> GetOrder:
    """Assemble the GetOrder query."""
    return GetOrder(orders=orders)


RedisCacheDep = Annotated[RedisCache, Depends(get_cache)]
