"""Order lifecycle states and the transitions between them."""

from enum import StrEnum

from app.domain.errors import InvalidOrderStateError


class OrderStatus(StrEnum):
    """Where an order is in its lifecycle."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    CANCELLED = "cancelled"


# The state machine, written as data instead of if/elif chains. Adding a state
# means adding one entry here, and an illegal transition is impossible to
# express. This is the piece to show in an interview.
ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING: frozenset({OrderStatus.CONFIRMED, OrderStatus.CANCELLED}),
    OrderStatus.CONFIRMED: frozenset({OrderStatus.SHIPPED, OrderStatus.CANCELLED}),
    OrderStatus.SHIPPED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
}

TERMINAL_STATUSES = frozenset({OrderStatus.SHIPPED, OrderStatus.CANCELLED})


def ensure_transition_allowed(current: OrderStatus, target: OrderStatus) -> None:
    """Raise unless ``current -> target`` is part of the state machine."""
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidOrderStateError(f"Cannot move an order from '{current}' to '{target}'")
