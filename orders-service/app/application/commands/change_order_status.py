"""Use cases that move an order through its lifecycle.

Both are thin on purpose: they load the aggregate, call a domain method and
persist. The rule lives in the aggregate, the orchestration lives here, and
the SQL lives in the adapter. If a use case ever contains an ``if`` about
business rules, that rule is in the wrong place.
"""

from dataclasses import dataclass

from app.application.ports import Clock, EventPublisher, OrderRepository, TransactionManager
from app.domain import OrderId, OrderNotFoundError, UtcDatetime

UNKNOWN_ORDER = "order-not-found"


@dataclass(frozen=True, slots=True, kw_only=True)
class ChangeOrderStatusResult:
    """Identity and instant of a lifecycle change."""

    order_id: OrderId
    occurred_at: UtcDatetime


class ConfirmOrder:
    """Confirms an order once stock has been reserved.

    The confirmation arrives asynchronously (a Kafka event from the inventory
    service in a later milestone), so the interesting question is idempotency:
    if the same event is delivered twice, the second call finds the order
    already confirmed and the state machine rejects it.
    """

    def __init__(
        self,
        *,
        orders: OrderRepository,
        publisher: EventPublisher,
        clock: Clock,
        transactions: TransactionManager,
    ) -> None:
        self._orders = orders
        self._publisher = publisher
        self._clock = clock
        self._transactions = transactions

    async def execute(self, order_id: OrderId) -> ChangeOrderStatusResult:
        """Move a pending order to confirmed, or fail loudly."""
        order = await self._orders.get_by_id(order_id)
        if order is None:
            raise OrderNotFoundError(f"{UNKNOWN_ORDER}: {order_id}")

        now = self._clock.now()
        order.confirm(now=now)

        await self._orders.save(order)
        await self._publisher.publish(order.pull_events())
        await self._transactions.commit()

        return ChangeOrderStatusResult(order_id=order.id, occurred_at=now)


class CancelOrder:
    """Cancels an order. This is the compensating action of ``ConfirmOrder``."""

    def __init__(
        self,
        *,
        orders: OrderRepository,
        publisher: EventPublisher,
        clock: Clock,
        transactions: TransactionManager,
    ) -> None:
        self._orders = orders
        self._publisher = publisher
        self._clock = clock
        self._transactions = transactions

    async def execute(self, order_id: OrderId, *, reason: str) -> ChangeOrderStatusResult:
        """Move an order to cancelled, recording why."""
        order = await self._orders.get_by_id(order_id)
        if order is None:
            raise OrderNotFoundError(f"{UNKNOWN_ORDER}: {order_id}")

        now = self._clock.now()
        order.cancel(reason=reason, now=now)

        await self._orders.save(order)
        await self._publisher.publish(order.pull_events())
        await self._transactions.commit()

        return ChangeOrderStatusResult(order_id=order.id, occurred_at=now)
