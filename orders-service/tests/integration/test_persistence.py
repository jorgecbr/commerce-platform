"""Integration tests: real PostgreSQL, real Redis.

The infrastructure lives outside the service, so the suite skips itself when
it is not reachable instead of failing. On CI both are started by the workflow;
locally they come from ``make up``.

What these tests prove, and unit tests cannot:
- the SQL is valid and the schema matches the domain
- optimistic concurrency really rejects a lost update
- the order and its outbox event land in the *same* transaction
- a constraint violation surfaces as a domain error
"""

import os
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.db.repositories import (
    OptimisticLockError,
    SqlAlchemyOrderRepository,
    SqlAlchemyOutboxPublisher,
    SqlAlchemyUnitOfWork,
    SystemClock,
    UuidGenerator,
)
from app.adapters.db.tables import OrderLineRow, OrderRow, OutboxRow, ProcessedMessageRow
from app.application.commands.change_order_status import CancelOrder, ConfirmOrder
from app.application.commands.place_order import (
    PlaceOrder,
    PlaceOrderLineRequest,
    PlaceOrderRequest,
)
from app.domain import OrderStatus, PricingService

DSN = os.getenv("TEST_DATABASE_DSN", "postgresql+psycopg://postgres@localhost:55432/orders")
REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/1")


def _postgres_available() -> bool:
    import psycopg

    plain = DSN.replace("postgresql+psycopg://", "postgresql://")
    try:
        with psycopg.connect(plain, connect_timeout=3):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.integration

if not _postgres_available():
    pytest.skip(
        "PostgreSQL is not reachable. Start it with 'make up' or run the CI workflow.",
        allow_module_level=True,
    )


@pytest_asyncio.fixture
async def sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Session factory bound to a clean database."""
    engine = create_async_engine(DSN, pool_size=5)
    async with engine.begin() as connection:
        await connection.execute(delete(ProcessedMessageRow))
        await connection.execute(delete(OutboxRow))
        await connection.execute(delete(OrderRow))
    yield async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def session(sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as value:
        yield value


def build_place_order(session: AsyncSession) -> PlaceOrder:
    return PlaceOrder(
        orders=SqlAlchemyOrderRepository(session),
        publisher=SqlAlchemyOutboxPublisher(session),
        clock=SystemClock(),
        ids=UuidGenerator(),
        transactions=SqlAlchemyUnitOfWork(session),
        pricing=PricingService(),
    )


def place_request() -> PlaceOrderRequest:
    return PlaceOrderRequest(
        customer_id="customer-42",
        lines=(
            PlaceOrderLineRequest(sku="SKU-001", quantity=2, unit_price=Decimal("10.00"), currency="USD"),
            PlaceOrderLineRequest(sku="SKU-002", quantity=1, unit_price=Decimal("25.50"), currency="USD"),
        ),
    )


class TestPersistence:
    @pytest.mark.asyncio
    async def test_order_and_its_event_are_committed_together(self, session: AsyncSession) -> None:
        result = await build_place_order(session).execute(place_request())

        row = await session.get(OrderRow, result.order_id)
        assert row is not None
        assert row.status == OrderStatus.PENDING.value
        assert row.total_amount == 4550
        assert row.version == 1

        events = (await session.execute(select(OutboxRow))).scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "order.placed"
        assert events[0].published_at is None
        total_payload = events[0].payload["total"]
        assert isinstance(total_payload, dict)
        assert total_payload["amount"] == 4550

    @pytest.mark.asyncio
    async def test_lines_are_persisted_and_reload_identically(self, session: AsyncSession) -> None:
        result = await build_place_order(session).execute(place_request())

        reloaded = await SqlAlchemyOrderRepository(session).get_by_id(result.order_id)
        assert reloaded is not None
        assert [line.sku.value for line in reloaded.lines] == ["SKU-001", "SKU-002"]
        assert reloaded.total.amount == 4550
        assert reloaded.currency == "USD"

    @pytest.mark.asyncio
    async def test_duplicate_sku_is_rejected_by_the_database_too(self, session: AsyncSession) -> None:
        # The domain already forbids a repeated SKU. This proves a write that
        # bypasses the domain - a migration, a backfill, a buggy script -
        # cannot break the invariant either.
        import sqlalchemy as sa

        await build_place_order(session).execute(place_request())
        order_id = await _any_order_id(session)

        with pytest.raises(sa.exc.IntegrityError):
            await session.execute(
                sa.insert(OrderLineRow),
                [
                    {
                        "order_id": order_id,
                        "sku": "SKU-001",
                        "quantity": 1,
                        "unit_price_amount": 999,
                        "unit_price_currency": "USD",
                    }
                ],
            )
            await session.commit()
        await session.rollback()

    @pytest.mark.asyncio
    async def test_optimistic_lock_rejects_a_lost_update(self, session: AsyncSession) -> None:
        result = await build_place_order(session).execute(place_request())
        repository = SqlAlchemyOrderRepository(session)

        order = await repository.get_by_id(result.order_id)
        assert order is not None
        order.confirm(now=order.updated_at)
        await repository.save(order)
        await session.commit()

        # A second worker loaded the same version before the first one saved.
        stale = await repository.get_by_id(result.order_id)
        assert stale is not None
        stale.version = 1
        stale.cancel(reason="stale writer", now=stale.updated_at)

        with pytest.raises(OptimisticLockError):
            await repository.save(stale)

    @pytest.mark.asyncio
    async def test_confirm_bumps_version_and_writes_the_event(
        self, session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        result = await build_place_order(session).execute(place_request())
        confirm = ConfirmOrder(
            orders=SqlAlchemyOrderRepository(session),
            publisher=SqlAlchemyOutboxPublisher(session),
            clock=SystemClock(),
            transactions=SqlAlchemyUnitOfWork(session),
        )
        await confirm.execute(result.order_id)

        # A fresh session on purpose: the UPDATE runs with
        # synchronize_session=False, so reading through the same session would
        # return the stale identity-map object instead of the committed row.
        async with sessionmaker() as reader:
            row = await reader.get(OrderRow, result.order_id)
        assert row is not None
        assert row.status == OrderStatus.CONFIRMED.value
        assert row.version == 2

        events = (await session.execute(select(OutboxRow))).scalars().all()
        assert [event.event_type for event in events] == ["order.placed", "order.confirmed"]

    @pytest.mark.asyncio
    async def test_cancel_is_reflected_in_the_database(
        self, session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        result = await build_place_order(session).execute(place_request())
        cancel = CancelOrder(
            orders=SqlAlchemyOrderRepository(session),
            publisher=SqlAlchemyOutboxPublisher(session),
            clock=SystemClock(),
            transactions=SqlAlchemyUnitOfWork(session),
        )
        await cancel.execute(result.order_id, reason="customer changed their mind")

        async with sessionmaker() as reader:
            row = await reader.get(OrderRow, result.order_id)
            events = (await reader.execute(select(OutboxRow))).scalars().all()

        assert row is not None
        assert row.status == OrderStatus.CANCELLED.value

        cancelled = [event for event in events if event.event_type == "order.cancelled"]
        assert cancelled[0].payload["reason"] == "customer changed their mind"


class TestOutboxRelayContract:
    @pytest.mark.asyncio
    async def test_unpublished_events_are_findable(self, session: AsyncSession) -> None:
        """The relay query depends on this index being usable."""
        await build_place_order(session).execute(place_request())

        pending = (
            (
                await session.execute(
                    select(OutboxRow).where(OutboxRow.published_at.is_(None)).order_by(OutboxRow.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(pending) == 1

    @pytest.mark.asyncio
    async def test_processed_messages_block_duplicates(self, session: AsyncSession) -> None:
        """At-least-once delivery plus a unique key gives exactly-once effects."""
        import sqlalchemy as sa

        message_id = str(uuid.uuid4())
        session.add(ProcessedMessageRow(consumer="orders-service", message_id=message_id))
        await session.commit()

        with pytest.raises(sa.exc.IntegrityError):
            session.add(ProcessedMessageRow(consumer="orders-service", message_id=message_id))
            await session.commit()
        await session.rollback()


async def _any_order_id(session: AsyncSession) -> uuid.UUID:
    order_id = await session.scalar(select(OrderRow.id).limit(1))
    assert order_id is not None
    return order_id
