"""Ports: the interfaces the application needs from the outside world.

Defined *here*, in the inner layer, and implemented in ``app.adapters``. That
is the dependency inversion: the arrow of dependency always points inwards,
towards the business. Swapping PostgreSQL for MongoDB, or Kafka for SQS, means
writing a new adapter and changing one line in the composition root — not
touching a single business rule.

``Protocol`` (structural typing) is used instead of an ABC because these
objects are collaborators, not base classes to inherit from. Tests get fakes
for free without registering them anywhere.
"""

from collections.abc import Sequence
from typing import Protocol

from app.domain import Order, OrderDomainEvent, OrderId, UtcDatetime


class OrderRepository(Protocol):
    """Persistence port for the Order aggregate.

    Only the aggregate is stored, never the read model: queries have their own
    port on purpose (see ``OrderQueryService``).
    """

    async def add(self, order: Order) -> None:
        """Insert a new aggregate."""
        ...

    async def get_by_id(self, order_id: OrderId) -> Order | None:
        """Load an aggregate, or ``None`` if it does not exist."""
        ...

    async def save(self, order: Order) -> None:
        """Persist an existing aggregate using optimistic concurrency.

        The adapter must fail when ``order.version`` does not match the stored
        row: two concurrent confirmations of the same order is a business bug,
        not something to silently overwrite.
        """
        ...


class EventPublisher(Protocol):
    """Outbound port for domain events.

    The in-process implementation buffers events into the outbox table so they
    are committed in the same transaction as the state change. Publishing to
    Kafka for real is a separate, retryable relay.
    """

    async def publish(self, events: Sequence[OrderDomainEvent]) -> None:
        """Buffer events so they commit together with the state change."""
        ...


class Clock(Protocol):
    """Time as a dependency.

    Never call ``datetime.now()`` in business logic: it makes time-dependent
    rules untestable.
    """

    def now(self) -> UtcDatetime:
        """Return the current time."""
        ...


class IdGenerator(Protocol):
    """Identity generation as a dependency, so tests can make ids deterministic."""

    def new_order_id(self) -> OrderId:
        """Return a brand new order identifier."""
        ...


class TransactionManager(Protocol):
    """Commit/rollback boundary for one unit of work."""

    async def commit(self) -> None:
        """Make the current unit of work permanent."""
        ...

    async def rollback(self) -> None:
        """Discard the current unit of work."""
        ...


class HealthProbe(Protocol):
    """Liveness/readiness probe used by the HTTP adapter."""

    async def check(self) -> bool:
        """Return whether the dependency is reachable."""
        ...
