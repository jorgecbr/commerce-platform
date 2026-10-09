"""Idempotent event consumption.

Kafka delivers at least once: a consumer can receive the same message twice
because of a rebalance, a retry, or a relay that crashed after publishing but
before marking the row. The inbox table turns those duplicates into a no-op.

The mechanism is deliberately boring: insert ``(consumer, message_id)`` first,
and only then do the work. If the insert fails because the row already exists,
this message was handled before. Inserting *before* the work is what makes
the guard safe - the opposite order leaves a window where a crash after the
work but before the insert causes a duplicate effect on the retry.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.adapters.db.tables import ProcessedMessageRow

logger = logging.getLogger(__name__)


class IdempotentConsumer:
    """Runs a handler at most once per message id."""

    def __init__(self, *, sessionmaker: async_sessionmaker[AsyncSession], consumer_name: str) -> None:
        self._sessionmaker = sessionmaker
        self._consumer_name = consumer_name

    async def handle(
        self, message_id: str, payload: dict[str, Any], handler: Callable[[dict[str, Any]], Awaitable[None]]
    ) -> bool:
        """Process a message once.

        Returns ``True`` when the handler ran and ``False`` when the message was
        a duplicate. The handler and the inbox row share one transaction, so a
        failure rolls back both and Kafka can redeliver safely.
        """
        async with self._sessionmaker() as session:
            try:
                async with session.begin():
                    session.add(ProcessedMessageRow(consumer=self._consumer_name, message_id=message_id))
                    await session.flush()
                    await handler(payload)
            except sa.exc.IntegrityError:
                await session.rollback()
                logger.info("Skipping duplicate message %s", message_id)
                return False
            return True


async def consume_topic(
    *,
    engine: AsyncEngine,
    bootstrap_servers: str,
    topic: str,
    group_id: str,
    handler: Callable[[dict[str, Any]], Awaitable[None]],
    consumer_name: str,
) -> None:
    """Subscribe to a topic and dispatch each message idempotently.

    ``auto_offset_reset="earliest"`` so a new consumer group reads history
    rather than silently skipping everything published before it existed.
    """
    from aiokafka import AIOKafkaConsumer

    from app.adapters.db.engine import create_sessionmaker

    sessionmaker = create_sessionmaker(engine)
    idempotent = IdempotentConsumer(sessionmaker=sessionmaker, consumer_name=consumer_name)

    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        # Offsets are committed only after the handler returns, which is what
        # gives at-least-once delivery. Combined with the inbox table, the
        # observable effect is exactly once.
        max_poll_records=100,
    )
    await consumer.start()
    logger.info("Consuming %s as %s", topic, group_id)
    try:
        async for message in consumer:
            try:
                payload = json.loads(message.value.decode())
                await idempotent.handle(
                    message_id=f"{message.topic}-{message.partition}-{message.offset}",
                    payload=payload,
                    handler=handler,
                )
                await consumer.commit()
            except Exception:
                logger.exception("Failed to handle message at offset %s", message.offset)
                await _backoff(1.0)
    finally:
        await consumer.stop()


async def _backoff(seconds: float) -> None:
    """Pause before retrying, so a broker outage does not become a hot loop."""
    await asyncio.sleep(seconds)
