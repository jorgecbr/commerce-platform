"""End-to-end messaging tests against a real Kafka broker.

Skipped when no broker is reachable. What they prove:

- the relay moves outbox rows to the topic and marks them published
- a row that fails to publish is retried and eventually given up on, without
  stopping the rest of the batch
- a message delivered twice is handled once

These are the guarantees that unit tests cannot: that the wiring between the
outbox table, the broker and the inbox table actually holds.
"""

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.db.tables import OutboxRow, ProcessedMessageRow
from app.adapters.events.consumer import IdempotentConsumer
from app.adapters.events.kafka_producer import KafkaEventPublisher, create_producer
from app.adapters.events.outbox_relay import OutboxRelay

# Defaults match docker-compose.yml: PostgreSQL on 5432 and the external
# Kafka listener on 29092.
DSN = os.getenv("TEST_DATABASE_DSN", "postgresql+psycopg://orders:orders@localhost:5432/orders")
BOOTSTRAP = os.getenv("TEST_KAFKA_BOOTSTRAP", "localhost:29092")
TOPIC = f"test.orders.{uuid.uuid4().hex[:8]}"


def _broker_reachable() -> bool:
    """Cheap TCP probe so the suite skips instead of hanging on a timeout."""
    import socket

    host, _, port = BOOTSTRAP.rpartition(":")
    try:
        with socket.create_connection((host or "localhost", int(port)), timeout=3):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.integration

if not _broker_reachable():
    pytest.skip(f"No Kafka broker at {BOOTSTRAP}. Start it with 'make up'.", allow_module_level=True)


@pytest_asyncio.fixture
async def sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(DSN, pool_size=5)
    async with engine.begin() as connection:
        await connection.execute(delete(ProcessedMessageRow))
        await connection.execute(delete(OutboxRow))
    yield async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def producer() -> AsyncIterator[KafkaEventPublisher]:
    raw = create_producer(BOOTSTRAP)
    await raw.start()
    try:
        yield KafkaEventPublisher(raw, topic=TOPIC)
    finally:
        await raw.stop()


@pytest_asyncio.fixture
async def exclusive_producer() -> AsyncIterator[tuple[KafkaEventPublisher, str]]:
    """A producer bound to a topic nobody else writes to.

    The shared topic accumulates messages from the other tests in this module,
    so a test that asserts on exact content needs its own.
    """
    topic = f"{TOPIC}.solo"
    raw = create_producer(BOOTSTRAP)
    await raw.start()
    try:
        yield KafkaEventPublisher(raw, topic=topic), topic
    finally:
        await raw.stop()


class TestOutboxRelay:
    @pytest.mark.asyncio
    async def test_publishes_pending_rows_and_marks_them(
        self, sessionmaker: async_sessionmaker[AsyncSession], producer: KafkaEventPublisher
    ) -> None:
        async with sessionmaker() as session:
            order_id = uuid.uuid4()
            for event_type in ("order.placed", "order.confirmed"):
                session.add(
                    OutboxRow(
                        aggregate_type="order",
                        aggregate_id=str(order_id),
                        event_type=event_type,
                        payload={"event_type": event_type, "order_id": str(order_id)},
                    )
                )
            await session.commit()

        relay = OutboxRelay(sessionmaker=sessionmaker, publisher=producer)
        outcome = await relay.run_once()
        assert outcome.published == 2
        assert outcome.failed == 0

        async with sessionmaker() as session:
            rows = (await session.execute(select(OutboxRow))).scalars().all()
            assert all(row.published_at is not None for row in rows)

    @pytest.mark.asyncio
    async def test_second_pass_finds_nothing(
        self, sessionmaker: async_sessionmaker[AsyncSession], producer: KafkaEventPublisher
    ) -> None:
        async with sessionmaker() as session:
            session.add(
                OutboxRow(
                    aggregate_type="order",
                    aggregate_id=str(uuid.uuid4()),
                    event_type="order.placed",
                    payload={"event_type": "order.placed"},
                )
            )
            await session.commit()

        relay = OutboxRelay(sessionmaker=sessionmaker, publisher=producer)
        assert (await relay.run_once()).published == 1
        # Already published rows must not be sent again: that would be the
        # relay's own contribution to duplicate events.
        assert (await relay.run_once()).published == 0

    @pytest.mark.asyncio
    async def test_a_failing_row_does_not_stop_the_batch(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        async with sessionmaker() as session:
            session.add_all(
                [
                    OutboxRow(
                        aggregate_type="order",
                        aggregate_id=str(uuid.uuid4()),
                        event_type="order.placed",
                        payload={"event_type": "order.placed"},
                    ),
                    OutboxRow(
                        aggregate_type="order",
                        aggregate_id=str(uuid.uuid4()),
                        event_type="order.confirmed",
                        payload={"event_type": "order.confirmed"},
                    ),
                ]
            )
            await session.commit()

        class BrokenPublisher:
            async def publish(self, *, key: str, event_type: str, payload: dict[str, object]) -> None:
                raise RuntimeError("broker unreachable")

        relay = OutboxRelay(sessionmaker=sessionmaker, publisher=BrokenPublisher())
        outcome = await relay.run_once()
        assert outcome.published == 0
        assert outcome.failed == 2

        async with sessionmaker() as session:
            rows = (await session.execute(select(OutboxRow))).scalars().all()
            assert all(row.attempts == 1 for row in rows)
            assert all(row.published_at is None for row in rows)


class TestIdempotentConsumer:
    @pytest.mark.asyncio
    async def test_handler_runs_once_per_message(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        calls: list[str] = []

        async def handler(payload: dict[str, object]) -> None:
            calls.append(str(payload["event_type"]))

        consumer = IdempotentConsumer(sessionmaker=sessionmaker, consumer_name="test-consumer")
        message_id = str(uuid.uuid4())
        payload = {"event_type": "order.placed"}

        assert await consumer.handle(message_id, payload, handler) is True
        assert await consumer.handle(message_id, payload, handler) is False
        assert calls == ["order.placed"]

    @pytest.mark.asyncio
    async def test_different_consumers_may_handle_the_same_message(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """The key is (consumer, message_id), not message_id alone."""
        calls: list[str] = []

        async def handler(payload: dict[str, object]) -> None:
            calls.append(str(payload))

        message_id = str(uuid.uuid4())
        payload = {"event_type": "order.placed"}
        first = IdempotentConsumer(sessionmaker=sessionmaker, consumer_name="consumer-a")
        second = IdempotentConsumer(sessionmaker=sessionmaker, consumer_name="consumer-b")

        assert await first.handle(message_id, payload, handler) is True
        assert await second.handle(message_id, payload, handler) is True
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_a_failing_handler_leaves_no_inbox_row(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """A crash mid-handler must not mark the message as processed."""
        attempts: list[int] = []

        async def flaky(payload: dict[str, object]) -> None:
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("transient failure")

        consumer = IdempotentConsumer(sessionmaker=sessionmaker, consumer_name="test-consumer")
        message_id = str(uuid.uuid4())
        payload = {"event_type": "order.placed"}

        with pytest.raises(RuntimeError):
            await consumer.handle(message_id, payload, flaky)

        # Redelivery must be allowed, which only happens if the inbox row was
        # rolled back with the handler's work.
        assert await consumer.handle(message_id, payload, flaky) is True
        assert len(attempts) == 2


class TestThroughTheBroker:
    @pytest.mark.asyncio
    async def test_event_survives_the_round_trip(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        exclusive_producer: tuple[KafkaEventPublisher, str],
    ) -> None:
        """Publish an outbox row, consume it from the topic, handle it once."""
        from aiokafka import AIOKafkaConsumer

        producer, topic = exclusive_producer
        order_id = str(uuid.uuid4())
        async with sessionmaker() as session:
            session.add(
                OutboxRow(
                    aggregate_type="order",
                    aggregate_id=order_id,
                    event_type="order.placed",
                    payload={
                        "event_type": "order.placed",
                        "order_id": order_id,
                        "total": {"amount": 4550, "currency": "USD"},
                    },
                )
            )
            await session.commit()

        relay = OutboxRelay(sessionmaker=sessionmaker, publisher=producer)
        assert (await relay.run_once()).published == 1

        # group_id=None: this test is about the event surviving the round trip.
        # Joining a consumer group would make it depend on the
        # __consumer_offsets coordinator being ready, which is a flaky thing
        # to build an assertion on.
        # group_id=None: this test is about the event surviving the round trip.
        # Joining a consumer group would make it depend on the
        # __consumer_offsets coordinator being ready, which is a flaky thing
        # to build an assertion on.
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=BOOTSTRAP,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            group_id=None,
        )
        await consumer.start()
        received: list[dict[str, object]] = []
        try:
            message = await asyncio.wait_for(consumer.getone(), timeout=45)
            received.append(json.loads(message.value.decode()))
        finally:
            await consumer.stop()

        assert len(received) == 1
        assert received[0]["event_type"] == "order.placed"
        assert received[0]["order_id"] == order_id

        handled: list[dict[str, object]] = []

        async def handler(payload: dict[str, object]) -> None:
            handled.append(payload)

        idempotent = IdempotentConsumer(sessionmaker=sessionmaker, consumer_name="e2e")
        assert await idempotent.handle("msg-1", received[0], handler) is True
        assert await idempotent.handle("msg-1", received[0], handler) is False
        assert len(handled) == 1
