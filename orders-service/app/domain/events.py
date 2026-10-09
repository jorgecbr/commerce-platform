"""Domain events.

A domain event is a fact that already happened in the business, named in the
ubiquitous language ("order placed", not "row inserted"). The aggregate
records them; publishing them to Kafka is the *adapter's* job, never the
aggregate's. That separation is what keeps the domain infrastructure-free.
"""

from dataclasses import dataclass
from uuid import UUID

from app.domain.money import Money
from app.domain.utc_datetime import UtcDatetime


@dataclass(frozen=True, slots=True)
class OrderPlaced:
    """A new order was created and is waiting for confirmation."""

    order_id: UUID
    customer_id: str
    total: Money
    occurred_at: UtcDatetime


@dataclass(frozen=True, slots=True)
class OrderConfirmed:
    """The order passed validation and stock was reserved. It is now committed."""

    order_id: UUID
    occurred_at: UtcDatetime


@dataclass(frozen=True, slots=True)
class OrderCancelled:
    """The order was cancelled. This is the compensating action for most failures."""

    order_id: UUID
    reason: str
    occurred_at: UtcDatetime


@dataclass(frozen=True, slots=True)
class OrderShipped:
    """The order left the warehouse."""

    order_id: UUID
    occurred_at: UtcDatetime


type OrderDomainEvent = OrderPlaced | OrderConfirmed | OrderCancelled | OrderShipped
