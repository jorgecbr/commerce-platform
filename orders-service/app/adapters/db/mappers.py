"""Translation between domain objects and database rows.

This is the anti-corruption layer in practice: `Money` becomes two columns, a
``tuple[OrderLine, ...]`` becomes a collection of rows, and the events become
JSON payloads. The domain never sees a column name and the tables never see a
business rule.
"""

from datetime import UTC, datetime

from app.adapters.db.tables import OrderLineRow, OrderRow
from app.domain import (
    Money,
    Order,
    OrderDomainEvent,
    OrderLine,
    OrderPlaced,
    OrderStatus,
    Sku,
    UtcDatetime,
)
from app.domain.events import OrderCancelled, OrderConfirmed, OrderShipped

EVENT_TYPE_NAMES: dict[type, str] = {
    OrderPlaced: "order.placed",
    OrderConfirmed: "order.confirmed",
    OrderCancelled: "order.cancelled",
    OrderShipped: "order.shipped",
}
EVENT_TYPES_BY_NAME = {name: cls for cls, name in EVENT_TYPE_NAMES.items()}


def event_type_name(event: OrderDomainEvent) -> str:
    """Return the wire name of a domain event, e.g. ``order.placed``."""
    return EVENT_TYPE_NAMES[type(event)]


def order_to_row(order: Order) -> OrderRow:
    """Build the row tree for an aggregate. Does not touch the session."""
    row = OrderRow(
        id=order.id,
        customer_id=order.customer_id,
        status=order.status.value,
        currency=order.currency,
        total_amount=order.total.amount,
        created_at=order.created_at.value,
        updated_at=order.updated_at.value,
        version=order.version,
    )
    row.lines = [
        OrderLineRow(
            sku=line.sku.value,
            quantity=line.quantity,
            unit_price_amount=line.unit_price.amount,
            unit_price_currency=line.unit_price.currency,
        )
        for line in order.lines
    ]
    return row


def row_to_order(row: OrderRow) -> Order:
    """Rebuild the aggregate from its row."""
    lines = tuple(
        OrderLine(
            sku=Sku(line.sku),
            quantity=line.quantity,
            unit_price=Money(line.unit_price_amount, line.unit_price_currency),
        )
        for line in sorted(row.lines, key=lambda item: item.sku)
    )
    return Order(
        id=row.id,
        customer_id=row.customer_id,
        status=OrderStatus(row.status),
        lines=lines,
        created_at=UtcDatetime(row.created_at),
        updated_at=UtcDatetime(row.updated_at),
        version=row.version,
    )


def event_to_payload(event: OrderDomainEvent) -> dict[str, object]:
    """Serialise a domain event into the JSON body sent over the wire."""
    payload: dict[str, object] = {
        "event_type": event_type_name(event),
        "occurred_at": event.occurred_at.value.isoformat(),
    }
    match event:
        case OrderPlaced(order_id, customer_id, total, _):
            payload |= {
                "order_id": str(order_id),
                "customer_id": customer_id,
                "total": {"amount": total.amount, "currency": total.currency},
            }
        case OrderConfirmed(order_id, _):
            payload["order_id"] = str(order_id)
        case OrderShipped(order_id, _):
            payload["order_id"] = str(order_id)
        case OrderCancelled(order_id, reason, _):
            payload |= {"order_id": str(order_id), "reason": reason}
    return payload


def payload_to_event(payload: dict[str, object]) -> OrderDomainEvent:
    """Rebuild a domain event received from the broker."""
    event_type = str(payload["event_type"])
    occurred_at = UtcDatetime.from_iso(str(payload["occurred_at"]))
    from uuid import UUID

    match EVENT_TYPES_BY_NAME[event_type]:
        case _ if event_type == "order.placed":
            total_raw = payload["total"]
            if not isinstance(total_raw, dict):
                raise ValueError(f"Malformed order.placed payload: {payload!r}")
            return OrderPlaced(
                order_id=UUID(str(payload["order_id"])),
                customer_id=str(payload["customer_id"]),
                total=Money(int(total_raw["amount"]), str(total_raw["currency"])),
                occurred_at=occurred_at,
            )
        case _ if event_type == "order.confirmed":
            return OrderConfirmed(order_id=UUID(str(payload["order_id"])), occurred_at=occurred_at)
        case _ if event_type == "order.shipped":
            return OrderShipped(order_id=UUID(str(payload["order_id"])), occurred_at=occurred_at)
        case _:
            return OrderCancelled(
                order_id=UUID(str(payload["order_id"])),
                reason=str(payload["reason"]),
                occurred_at=occurred_at,
            )


def utc_now() -> datetime:
    """Return the current time as an aware datetime, for bookkeeping columns."""
    return datetime.now(UTC)
