"""SQLAlchemy implementations of the application ports.

The repository writes the aggregate with optimistic concurrency, and the unit
of work is the only place that commits. Nothing here contains a business
rule: an invalid order never reaches this code, because the aggregate raises
before it can be persisted.
"""

from collections.abc import Sequence
from uuid import uuid4

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.mappers import event_to_payload, event_type_name, order_to_row, row_to_order
from app.adapters.db.tables import OrderLineRow, OrderRow, OutboxRow
from app.domain import DuplicateSkuError, Order, OrderDomainEvent, OrderId, UtcDatetime


class OptimisticLockError(Exception):
    """Another transaction changed the row after we loaded it.

    Raised instead of silently overwriting, because overwriting a lifecycle
    transition is how duplicate orders and double charges happen.
    """


def _translate_integrity_error(exc: IntegrityError) -> Exception:
    """Turn a database constraint violation into a domain-shaped error."""
    detail = str(getattr(exc, "orig", exc)).lower()
    if "uq_order_lines_order_sku" in detail:
        return DuplicateSkuError("The same SKU appears more than once in the order")
    return exc


class SqlAlchemyOrderRepository:
    """Implements ``app.application.ports.OrderRepository``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, order: Order) -> None:
        """Insert a brand new aggregate."""
        self._session.add(order_to_row(order))
        # Flushed early so a constraint violation surfaces here, where the
        # traceback still points at the use case, instead of at commit time.
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise _translate_integrity_error(exc) from exc

    async def get_by_id(self, order_id: OrderId) -> Order | None:
        """Load the aggregate, or ``None`` when it does not exist."""
        row = await self._session.get(OrderRow, order_id)
        return None if row is None else row_to_order(row)

    async def save(self, order: Order) -> None:
        """Persist changes using optimistic concurrency.

        The WHERE clause carries the version that was loaded. If it matches no
        rows, another transaction committed first and we refuse to continue
        rather than overwriting a lifecycle transition.
        """
        expected_version = order.version - 1
        result = await self._session.execute(
            update(OrderRow)
            .where(OrderRow.id == order.id, OrderRow.version == expected_version)
            .values(
                status=order.status.value,
                currency=order.currency,
                total_amount=order.gross_total.amount,
                discount_amount=order.discount.amount,
                updated_at=order.updated_at.value,
                version=order.version,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            raise OptimisticLockError(
                f"Order {order.id} changed concurrently (expected version {expected_version})"
            )

        await self._replace_lines(order)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # The same constraint violation can surface on save, not only on
            # add: a caller can rebuild the line collection before persisting.
            raise _translate_integrity_error(exc) from exc

    async def _replace_lines(self, order: Order) -> None:
        """Rewrite the line collection so the mapping stays single-path.

        An order's lines never change after confirmation, so a delete plus
        insert costs nothing at scale and removes a whole class of
        add/remove/update bookkeeping bugs.
        """
        await self._session.execute(delete(OrderLineRow).where(OrderLineRow.order_id == order.id))
        if order.lines:
            await self._session.execute(
                insert(OrderLineRow),
                [
                    {
                        "order_id": order.id,
                        "sku": line.sku.value,
                        "quantity": line.quantity,
                        "unit_price_amount": line.unit_price.amount,
                        "unit_price_currency": line.unit_price.currency,
                    }
                    for line in order.lines
                ],
            )


class SqlAlchemyOutboxPublisher:
    """Implements ``app.application.ports.EventPublisher``.

    Events are buffered as rows inside the current transaction; a separate
    relay publishes them to the broker afterwards. Nothing touches Kafka from
    here, and that is exactly what makes the write atomic.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish(self, events: Sequence[OrderDomainEvent]) -> None:
        """Buffer events as outbox rows in the current transaction."""
        for event in events:
            self._session.add(
                OutboxRow(
                    aggregate_type="order",
                    aggregate_id=str(event.order_id),
                    event_type=event_type_name(event),
                    payload=event_to_payload(event),
                )
            )
        await self._session.flush()


class SqlAlchemyUnitOfWork:
    """Implements ``app.application.ports.TransactionManager``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        """Make the order and its outbox entry durable together."""
        await self._session.commit()

    async def rollback(self) -> None:
        """Discard everything written since the last commit."""
        await self._session.rollback()


class SystemClock:
    """Implements ``app.application.ports.Clock``."""

    def now(self) -> UtcDatetime:
        """Return the current UTC instant."""
        return UtcDatetime.now()


class UuidGenerator:
    """Implements ``app.application.ports.IdGenerator``."""

    def new_order_id(self) -> OrderId:
        """Return a new order identifier."""
        return uuid4()


async def load_orders_by_ids(session: AsyncSession, ids: Sequence[OrderId]) -> list[Order]:
    """Load several aggregates at once, used by the query side."""
    if not ids:
        return []
    result = await session.execute(select(OrderRow).where(OrderRow.id.in_(list(ids))))
    return [row_to_order(row) for row in result.scalars().all()]


__all__ = [
    "OptimisticLockError",
    "SqlAlchemyOrderRepository",
    "SqlAlchemyOutboxPublisher",
    "SqlAlchemyUnitOfWork",
    "SystemClock",
    "UuidGenerator",
    "load_orders_by_ids",
]
