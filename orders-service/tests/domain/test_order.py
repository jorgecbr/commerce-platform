"""The Order aggregate: invariants, state machine and domain events."""

from uuid import UUID

import pytest

from app.domain import (
    DuplicateSkuError,
    EmptyOrderError,
    InvalidOrderStateError,
    Order,
    OrderCancelled,
    OrderConfirmed,
    OrderLine,
    OrderPlaced,
    OrderShipped,
    OrderStatus,
    TooManyLinesError,
)
from tests.conftest import FROZEN_NOW, LATER, build_line, build_lines

ORDER_ID = UUID("11111111-1111-1111-1111-111111111111")
CUSTOMER = "customer-42"


def place(lines: tuple[OrderLine, ...] | None = None, customer: str = CUSTOMER) -> Order:
    return Order.place(
        order_id=ORDER_ID,
        customer_id=customer,
        lines=lines if lines is not None else build_lines(),
        now=FROZEN_NOW,
    )


class TestInvariants:
    def test_starts_pending_at_version_one(self) -> None:
        order = place()
        assert order.status is OrderStatus.PENDING
        assert order.version == 1
        assert order.created_at == order.updated_at == FROZEN_NOW

    def test_rejects_empty_order(self) -> None:
        with pytest.raises(EmptyOrderError):
            place(lines=())

    def test_rejects_duplicate_sku(self) -> None:
        # Two lines with the same SKU would mean two prices for one product.
        with pytest.raises(DuplicateSkuError):
            place(lines=(build_line("SKU-001", 1), build_line("SKU-001", 2)))

    def test_rejects_more_than_fifty_lines(self) -> None:
        lines = tuple(build_line(f"SKU-{i:03d}", 1) for i in range(51))
        with pytest.raises(TooManyLinesError):
            place(lines=lines)

    def test_accepts_exactly_fifty_lines(self) -> None:
        lines = tuple(build_line(f"SKU-{i:03d}", 1) for i in range(50))
        assert len(place(lines=lines).lines) == 50


class TestTotals:
    def test_total_is_the_sum_of_line_totals(self) -> None:
        # 2 x 10.00 + 1 x 25.50 = 45.50
        assert place().total.amount == 4550

    def test_currency_comes_from_the_lines(self) -> None:
        assert place().currency == "USD"

    def test_total_is_read_only_by_construction(self) -> None:
        order = place()
        before = order.total
        order.confirm(now=LATER)
        assert order.total == before  # confirming never changes the amount


class TestStateMachine:
    def test_confirm_moves_to_confirmed(self) -> None:
        order = place()
        order.confirm(now=LATER)
        assert order.status is OrderStatus.CONFIRMED
        assert order.version == 2
        assert order.updated_at == LATER

    def test_confirmed_order_can_ship(self) -> None:
        order = place()
        order.confirm(now=LATER)
        order.ship(now=LATER)
        assert order.status is OrderStatus.SHIPPED

    def test_shipped_is_terminal(self) -> None:
        order = place()
        order.confirm(now=LATER)
        order.ship(now=LATER)
        with pytest.raises(InvalidOrderStateError):
            order.cancel(reason="changed my mind", now=LATER)

    def test_cancelled_is_terminal(self) -> None:
        order = place()
        order.cancel(reason="out of stock", now=LATER)
        with pytest.raises(InvalidOrderStateError):
            order.confirm(now=LATER)

    def test_cannot_ship_a_pending_order(self) -> None:
        with pytest.raises(InvalidOrderStateError):
            place().ship(now=LATER)

    def test_confirmed_order_is_not_modifiable(self) -> None:
        order = place()
        order.confirm(now=LATER)
        assert not order.is_modifiable

    def test_pending_order_is_modifiable(self) -> None:
        assert place().is_modifiable


class TestDomainEvents:
    def test_placing_records_one_event(self) -> None:
        events = place().events
        assert len(events) == 1
        assert isinstance(events[0], OrderPlaced)
        assert events[0].total.amount == 4550

    def test_transitions_record_events_in_order(self) -> None:
        order = place()
        order.confirm(now=LATER)
        order.ship(now=LATER)
        assert [type(e) for e in order.events] == [OrderPlaced, OrderConfirmed, OrderShipped]

    def test_cancellation_carries_the_reason(self) -> None:
        order = place()
        order.cancel(reason="customer changed their mind", now=LATER)
        event = order.events[-1]
        assert isinstance(event, OrderCancelled)
        assert event.reason == "customer changed their mind"

    def test_pull_events_returns_and_clears(self) -> None:
        order = place()
        first = order.pull_events()
        assert len(first) == 1
        assert order.pull_events() == ()  # never published twice

    def test_pull_events_keeps_later_events(self) -> None:
        order = place()
        order.pull_events()
        order.confirm(now=LATER)
        assert [type(e) for e in order.pull_events()] == [OrderConfirmed]

    def test_failed_transition_records_nothing(self) -> None:
        order = place()
        with pytest.raises(InvalidOrderStateError):
            order.ship(now=LATER)
        assert len(order.events) == 1
        assert order.version == 1
