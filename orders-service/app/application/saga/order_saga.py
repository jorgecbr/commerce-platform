"""Order saga.

A confirmed order depends on stock that lives in another service, and there
is no transaction spanning both databases. The saga is what makes that safe:

    place order ──▶ order.placed ──▶ inventory reserves
                                        │
                        ┌───────────────┴───────────────┐
                  reserved                          rejected
                        │                               │
                        ▼                               ▼
                   order.confirmed                order.cancelled ──▶ release

Two properties carry the whole design:

**Every step has a compensating action.** Confirm is undone by cancel, a
reservation is undone by a release. A business action that cannot be undone
does not belong in a saga, which is why shipping is deliberately outside it.

**The orchestrator is one service.** orders-service decides what happens next
instead of every service reacting to every event. Choreography spreads the
decision across N handlers and makes the flow something you reconstruct by
reading all of them; orchestration keeps it readable in one file, at the cost
of the orchestrator knowing the others exist.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class SagaState(StrEnum):
    """Where an order is in the distributed transaction."""

    STARTED = "started"
    AWAITING_INVENTORY = "awaiting_inventory"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


TERMINAL_SAGA_STATES = frozenset({SagaState.CONFIRMED, SagaState.CANCELLED})


class SagaEvent(StrEnum):
    """What the inventory service can tell us about a reservation."""

    RESERVED = "inventory.reserved"
    REJECTED = "inventory.rejected"


class StaleSagaEventError(Exception):
    """An event arrived for a saga that already reached a terminal state."""


@dataclass(frozen=True, slots=True)
class SagaOutcome:
    """What to do next, given one incoming event.

    ``cancel_reason`` travels with the outcome so the compensating action is
    explainable in the order's own event stream, instead of appearing as a
    silent status change.
    """

    state: SagaState
    confirm: bool
    cancel_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ReservationLine:
    """One SKU and how many units an order needs."""

    sku: str
    quantity: int


@dataclass(frozen=True, slots=True)
class InventoryReservation:
    """What the inventory service was asked to set aside."""

    order_id: UUID
    lines: tuple[ReservationLine, ...]

    @classmethod
    def from_lines(cls, order_id: UUID, lines: tuple) -> "InventoryReservation":  # type: ignore[type-arg]
        """Build the reservation from an aggregate's line collection."""
        return cls(
            order_id=order_id,
            lines=tuple(ReservationLine(line.sku.value, line.quantity) for line in lines),
        )

    def to_payload(self) -> dict[str, object]:
        """Serialise for the ``order.placed`` event."""
        return {
            "order_id": str(self.order_id),
            "lines": [{"sku": line.sku, "quantity": line.quantity} for line in self.lines],
        }


def decide(current: SagaState, incoming: SagaEvent) -> SagaOutcome:
    """Advance the saga for one incoming event.

    Pure on purpose: the decision is data, so it can be tested exhaustively
    without a broker, a database or a clock.
    """
    if current in TERMINAL_SAGA_STATES:
        # A terminal saga ignores late events. A reservation that arrives after
        # the order was cancelled must never confirm an order the customer has
        # already abandoned.
        raise StaleSagaEventError(f"Saga is already in terminal state '{current}'")

    if incoming is SagaEvent.RESERVED:
        return SagaOutcome(state=SagaState.CONFIRMED, confirm=True)

    return SagaOutcome(
        state=SagaState.CANCELLED,
        confirm=False,
        cancel_reason="stock_unavailable",
    )
