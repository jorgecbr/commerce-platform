"""Background worker.

Two jobs that must not run inside a request:

* the **outbox relay**, which moves committed events to Kafka;
* the **saga consumer**, which reacts to what the inventory service says.

Both run in this process rather than in the API for a reason that matters
under load: the API must stay responsive when the broker is slow. A request
that waits for Kafka inherits its latency, and a broker outage becomes an API
outage. Here it only delays the relay's next poll.

Run it with::

    uv run python -m app.worker

The API process and this one are the same code with different entry points,
so they cannot drift apart.
"""

import asyncio
import contextlib
import logging
from typing import Any

from aiokafka import AIOKafkaConsumer

from app.adapters.db.engine import create_engine, create_sessionmaker
from app.adapters.db.repositories import (
    SqlAlchemyOrderRepository,
    SqlAlchemyOutboxPublisher,
    SqlAlchemyUnitOfWork,
    SystemClock,
)
from app.adapters.events.consumer import IdempotentConsumer
from app.adapters.events.kafka_producer import KafkaEventPublisher, create_producer
from app.adapters.events.outbox_relay import OutboxRelay
from app.application.saga.order_saga import SagaEvent, SagaState, decide
from app.config import get_settings

logger = logging.getLogger(__name__)


async def handle_inventory_event(payload: dict[str, Any]) -> None:
    """Apply what the inventory service reported to the saga.

    Wired as a handler so the idempotent consumer can guard it: the broker
    delivers at least once, and confirming an order twice must be a no-op
    rather than a second state transition.
    """
    event_type = str(payload.get("event_type", ""))
    order_id = payload.get("order_id")
    if order_id is None:
        logger.warning("Ignoring inventory event without order_id: %s", payload)
        return

    from uuid import UUID

    settings = get_settings()
    engine = create_engine(dsn=settings.async_dsn, pool_size=2)
    sessionmaker = create_sessionmaker(engine)
    try:
        async with sessionmaker() as session:
            repository = SqlAlchemyOrderRepository(session)
            order = await repository.get_by_id(UUID(str(order_id)))
            if order is None:
                logger.warning("Inventory event for unknown order %s", order_id)
                return

            incoming = SagaEvent.RESERVED if event_type == "inventory.reserved" else SagaEvent.REJECTED
            outcome = decide(SagaState.AWAITING_INVENTORY, incoming)
            now = SystemClock().now()

            if outcome.confirm:
                order.confirm(now=now)
            else:
                order.cancel(reason=outcome.cancel_reason or "stock_unavailable", now=now)

            await repository.save(order)
            await SqlAlchemyOutboxPublisher(session).publish(order.pull_events())
            await SqlAlchemyUnitOfWork(session).commit()
            logger.info("Order %s moved to %s after %s", order_id, outcome.state, event_type)
    finally:
        await engine.dispose()


async def main() -> None:
    """Start the relay and the saga consumer until cancelled."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("Worker starting")

    engine = create_engine(dsn=settings.async_dsn, pool_size=5)
    sessionmaker = create_sessionmaker(engine)

    producer = create_producer(settings.KAFKA_BOOTSTRAP_SERVERS)
    await producer.start()
    publisher = KafkaEventPublisher(producer, topic=settings.KAFKA_ORDERS_TOPIC)

    relay = OutboxRelay(sessionmaker=sessionmaker, publisher=publisher)

    # The consumer needs its own group so a redeploy does not rewind the
    # offsets it already processed.
    consumer = AIOKafkaConsumer(
        settings.KAFKA_INVENTORY_TOPIC,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=f"{settings.KAFKA_CONSUMER_GROUP}-saga",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()

    idempotent = IdempotentConsumer(
        sessionmaker=sessionmaker, consumer_name=f"{settings.KAFKA_CONSUMER_GROUP}-saga"
    )

    async def saga_loop() -> None:
        import json

        async for message in consumer:
            payload = json.loads(message.value.decode())
            try:
                await idempotent.handle(
                    message_id=f"{message.topic}-{message.partition}-{message.offset}",
                    payload=payload,
                    handler=handle_inventory_event,
                )
                await consumer.commit()
            except Exception:
                logger.exception("Failed to handle %s", payload.get("event_type"))
                await asyncio.sleep(1)

    tasks = [asyncio.create_task(relay.run_forever()), asyncio.create_task(saga_loop())]
    logger.info("Relay and saga consumer running")
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Worker stopping")
    finally:
        for task in tasks:
            task.cancel()
        with contextlib.suppress(Exception):
            await consumer.stop()
        await producer.stop()
        await engine.dispose()


if __name__ == "__main__":  # pragma: no cover - process entry point
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
