"""Saga tests.

Pure decision logic, so it is tested exhaustively with no infrastructure.
These are the cases that decide whether a customer gets charged for something
that cannot be shipped.
"""

from uuid import UUID

import pytest

from app.application.saga.order_saga import (
    InventoryReservation,
    ReservationLine,
    SagaEvent,
    SagaOutcome,
    SagaState,
    StaleSagaEventError,
    decide,
)
from app.domain import Money, Order, OrderLine, Sku, UtcDatetime

ORDER_ID = UUID("11111111-1111-1111-1111-111111111111")
NOW = UtcDatetime.from_iso("2026-03-01T10:00:00+00:00")


class TestHappyPath:
    def test_reservation_confirms_the_order(self) -> None:
        outcome = decide(SagaState.AWAITING_INVENTORY, SagaEvent.RESERVED)
        assert outcome == SagaOutcome(state=SagaState.CONFIRMED, confirm=True)

    def test_confirmation_carries_no_cancel_reason(self) -> None:
        assert decide(SagaState.AWAITING_INVENTORY, SagaEvent.RESERVED).cancel_reason is None


class TestCompensation:
    def test_rejection_cancels_the_order(self) -> None:
        outcome = decide(SagaState.AWAITING_INVENTORY, SagaEvent.REJECTED)
        assert outcome.state is SagaState.CANCELLED
        assert outcome.confirm is False

    def test_rejection_carries_a_reason(self) -> None:
        # The reason lands in OrderCancelled, so the order's history explains
        # why it was cancelled instead of just showing a status.
        outcome = decide(SagaState.AWAITING_INVENTORY, SagaEvent.REJECTED)
        assert outcome.cancel_reason == "stock_unavailable"


class TestTerminalStates:
    @pytest.mark.parametrize("terminal", [SagaState.CONFIRMED, SagaState.CANCELLED])
    def test_terminal_saga_rejects_any_further_event(self, terminal: SagaState) -> None:
        with pytest.raises(StaleSagaEventError):
            decide(terminal, SagaEvent.RESERVED)

    def test_late_reservation_cannot_revive_a_cancelled_order(self) -> None:
        """The scenario this whole design exists for.

        Stock is released because the order was cancelled, and then the
        reservation confirmation arrives late. Confirming here would charge a
        customer for an order that no longer exists.
        """
        cancelled = decide(SagaState.AWAITING_INVENTORY, SagaEvent.REJECTED)
        assert cancelled.state is SagaState.CANCELLED

        with pytest.raises(StaleSagaEventError):
            decide(cancelled.state, SagaEvent.RESERVED)


class TestEveryCombination:
    def test_all_pairs_are_accounted_for(self) -> None:
        """Every (state, event) pair either decides or raises - never silently."""
        open_states = [s for s in SagaState if s not in (SagaState.CONFIRMED, SagaState.CANCELLED)]
        for state in SagaState:
            for event in SagaEvent:
                if state in (SagaState.CONFIRMED, SagaState.CANCELLED):
                    with pytest.raises(StaleSagaEventError):
                        decide(state, event)
                else:
                    outcome = decide(state, event)
                    assert outcome.state in (SagaState.CONFIRMED, SagaState.CANCELLED)

        assert open_states  # guards against the list silently being empty


class TestReservationPayload:
    def test_built_from_the_aggregate(self) -> None:
        lines = (
            OrderLine(sku=Sku("SKU-001"), quantity=2, unit_price=Money(1000, "USD")),
            OrderLine(sku=Sku("SKU-002"), quantity=5, unit_price=Money(250, "USD")),
        )
        order = Order.place(order_id=ORDER_ID, customer_id="customer-42", lines=lines, now=NOW)

        reservation = InventoryReservation.from_lines(order.id, order.lines)
        assert reservation.order_id == ORDER_ID
        assert reservation.lines == (
            ReservationLine("SKU-001", 2),
            ReservationLine("SKU-002", 5),
        )

    def test_payload_is_json_ready(self) -> None:
        reservation = InventoryReservation(order_id=ORDER_ID, lines=(ReservationLine("SKU-001", 2),))
        assert reservation.to_payload() == {
            "order_id": "11111111-1111-1111-1111-111111111111",
            "lines": [{"sku": "SKU-001", "quantity": 2}],
        }
