"""Database engine and session management.

One engine per process, one session per request. The pool settings are
deliberate: a connection pool that is too large is a queue in disguise, and
PostgreSQL degrades badly when the active connections approach the server
limit.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(*, dsn: str, echo: bool = False, pool_size: int = 10) -> AsyncEngine:
    """Build the async engine.

    ``pool_pre_ping`` costs one cheap round trip per checkout and is what
    prevents the classic "the connection was closed by the server" error after
    a database restart or an idle timeout.
    """
    return create_async_engine(
        url=dsn,
        echo=echo,
        pool_size=pool_size,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=1800,
        hide_parameters=True,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory.

    ``autoflush=False`` because the use cases control exactly when state is
    written: the outbox entry and the order must land in the same
    transaction, and an implicit flush would break that ordering.
    """
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )


@asynccontextmanager
async def session_scope(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Provide a session and roll back anything left uncommitted."""
    async with sessionmaker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
