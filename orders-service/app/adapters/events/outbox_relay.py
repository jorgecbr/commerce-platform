"""Outbox relay.

Moves rows from ``outbox_events`` to Kafka. This component is the only thing
that publishes order events, and it runs *outside* the request transaction.

Why a relay instead of publishing inline:

* inline publishing cannot be atomic with the database write, so a crash
  between the two loses an event or invents one;
* a slow or unavailable broker must not slow down or fail the API;
* publishing becomes retryable independently, with backoff and a dead letter.

The relay is deliberately at-least-once. Rows are published first and marked
after, so a crash in between publishes the same event twice. Consumers are
therefore required to be idempotent, which is what the ``processed_messages``
table is for.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.adapters.db.tables import OutboxRow

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BATCH_SIZE = 100


class EventSink(Protocol):
    """Where the relay sends events.

    Declared as a Protocol so the relay can be tested with a failing stub
    without a real broker, and so a future publisher (SQS, NATS) only has to
    satisfy this interface.
    """

    async def publish(self, *, key: str, event_type: str, payload: dict[str, Any]) -> None:
        """Send one event, keyed by aggregate so ordering is preserved."""
        ...


@dataclass(frozen=True, slots=True)
class RelayOutcome:
    """What one relay pass did, for logging and metrics."""

    published: int
    failed: int

    @property
    def total(self) -> int:
        """Return how many rows this pass looked at."""
        return self.published + self.failed


class OutboxRelay:
    """Publishes pending outbox rows and marks them once they land."""

    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        publisher: EventSink,
        poll_interval: float = 1.0,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._publisher = publisher
        self._poll_interval = poll_interval
        self._batch_size = batch_size

    async def run_once(self) -> RelayOutcome:
        """Publish one batch and return what happened."""
        async with self._sessionmaker() as session:
            pending = (
                (
                    await session.execute(
                        select(OutboxRow)
                        .where(OutboxRow.published_at.is_(None))
                        .order_by(OutboxRow.id)
                        .limit(self._batch_size)
                    )
                )
                .scalars()
                .all()
            )

            if not pending:
                return RelayOutcome(published=0, failed=0)

            published = 0
            for row in pending:
                try:
                    await self._publisher.publish(
                        key=row.aggregate_id,
                        event_type=row.event_type,
                        payload=row.payload,
                    )
                except Exception as exc:
                    attempts = row.attempts + 1
                    logger.warning(
                        "Failed to publish outbox row %s (attempt %s/%s): %s",
                        row.id,
                        attempts,
                        MAX_ATTEMPTS,
                        exc,
                    )
                    await session.execute(
                        update(OutboxRow)
                        .where(OutboxRow.id == row.id)
                        .values(attempts=attempts, last_error=str(exc)[:512])
                    )
                    # Give up rather than spin forever on a permanently bad
                    # payload; the row stays unpublished for inspection.
                    if attempts >= MAX_ATTEMPTS:
                        logger.error("Outbox row %s exceeded retries, skipping", row.id)
                    continue

                await session.execute(
                    update(OutboxRow).where(OutboxRow.id == row.id).values(published_at=_now())
                )
                published += 1

            await session.commit()
            return RelayOutcome(published=published, failed=len(pending) - published)

    async def run_forever(self) -> None:
        """Poll until cancelled. The sleep keeps an idle relay cheap."""
        logger.info("Outbox relay started")
        while True:
            outcome = await self.run_once()
            if outcome.total == 0:
                await asyncio.sleep(self._poll_interval)
            else:
                logger.info("Outbox relay published %s, failed %s", outcome.published, outcome.failed)


def _now() -> datetime:
    """Return the current instant for the ``published_at`` column."""
    from app.adapters.db.mappers import utc_now

    return utc_now()


async def build_relay(engine: AsyncEngine, publisher: EventSink) -> OutboxRelay:
    """Build a relay from an engine, used by the worker entry point."""
    from app.adapters.db.engine import create_sessionmaker

    return OutboxRelay(sessionmaker=create_sessionmaker(engine), publisher=publisher)
