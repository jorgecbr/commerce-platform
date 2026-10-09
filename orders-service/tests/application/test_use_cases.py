"""Use cases tested against fakes, proving the application layer needs no I/O."""

from decimal import Decimal

import pytest

from app.application.commands.change_order_status import CancelOrder, ConfirmOrder
from app.application.commands.place_order import PlaceOrder, PlaceOrderLineRequest, PlaceOrderRequest
from app.domain import OrderNotFoundError, OrderPlaced, OrderStatus, PricingService
from tests.conftest import (
    LATER,
    FrozenClock,
    InMemoryOrderRepository,
    RecordingEventPublisher,
    RecordingTransactionManager,
    SequentialIdGenerator,
)


def request_with(*lines: tuple[str, int, str]) -> PlaceOrderRequest:
    return PlaceOrderRequest(
        customer_id="customer-42",
        lines=tuple(
            PlaceOrderLineRequest(sku=sku, quantity=qty, unit_price=Decimal(price), currency="USD")
            for sku, qty, price in lines
        ),
    )


@pytest.fixture
def place_order(
    orders: InMemoryOrderRepository,
    publisher: RecordingEventPublisher,
    clock: FrozenClock,
    ids: SequentialIdGenerator,
    transactions: RecordingTransactionManager,
) -> PlaceOrder:
    return PlaceOrder(
        orders=orders,
        publisher=publisher,
        clock=clock,
        ids=ids,
        transactions=transactions,
        pricing=PricingService(),
    )


class TestPlaceOrder:
    @pytest.mark.asyncio
    async def test_stores_and_returns_the_new_order(
        self,
        place_order: PlaceOrder,
        orders: InMemoryOrderRepository,
    ) -> None:
        result = await place_order.execute(request_with(("SKU-001", 2, "10.00")))

        assert len(orders.orders) == 1
        assert result.order_id in orders.orders
        assert orders.orders[result.order_id].status is OrderStatus.PENDING

    @pytest.mark.asyncio
    async def test_converts_transport_types_into_domain_types(
        self,
        place_order: PlaceOrder,
    ) -> None:
        # The use case receives Decimal and str; the aggregate only ever sees
        # Money, Sku and UtcDatetime.
        result = await place_order.execute(request_with(("SKU-001", 3, "12.50")))
        assert result.total.amount == 3750

    @pytest.mark.asyncio
    async def test_applies_volume_pricing_to_the_result(
        self,
        place_order: PlaceOrder,
    ) -> None:
        result = await place_order.execute(request_with(("SKU-001", 10, "10.00")))
        assert result.total.amount == 9500  # 100.00 - 5%

    @pytest.mark.asyncio
    async def test_publishes_events_before_committing(
        self,
        place_order: PlaceOrder,
        publisher: RecordingEventPublisher,
        transactions: RecordingTransactionManager,
    ) -> None:
        await place_order.execute(request_with(("SKU-001", 1, "10.00")))
        assert [type(e) for e in publisher.published] == [OrderPlaced]
        assert transactions.commits == 1

    @pytest.mark.asyncio
    async def test_invalid_input_never_reaches_the_store(
        self,
        place_order: PlaceOrder,
        orders: InMemoryOrderRepository,
        transactions: RecordingTransactionManager,
    ) -> None:
        from app.domain import EmptyOrderError

        with pytest.raises(EmptyOrderError):
            await place_order.execute(request_with())
        assert orders.orders == {}
        assert transactions.commits == 0


@pytest.fixture
def confirm_order(
    orders: InMemoryOrderRepository,
    publisher: RecordingEventPublisher,
    clock: FrozenClock,
    transactions: RecordingTransactionManager,
) -> ConfirmOrder:
    return ConfirmOrder(orders=orders, publisher=publisher, clock=clock, transactions=transactions)


@pytest.fixture
def cancel_order(
    orders: InMemoryOrderRepository,
    publisher: RecordingEventPublisher,
    clock: FrozenClock,
    transactions: RecordingTransactionManager,
) -> CancelOrder:
    return CancelOrder(orders=orders, publisher=publisher, clock=clock, transactions=transactions)


class TestConfirmOrder:
    @pytest.mark.asyncio
    async def test_confirms_a_pending_order(
        self,
        confirm_order: ConfirmOrder,
        place_order: PlaceOrder,
        orders: InMemoryOrderRepository,
    ) -> None:
        placed = await place_order.execute(request_with(("SKU-001", 1, "10.00")))
        await confirm_order.execute(placed.order_id)
        assert orders.orders[placed.order_id].status is OrderStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_rejects_an_unknown_order(self, confirm_order: ConfirmOrder) -> None:
        from uuid import uuid4

        with pytest.raises(OrderNotFoundError):
            await confirm_order.execute(uuid4())

    @pytest.mark.asyncio
    async def test_is_not_idempotent_by_design(
        self,
        confirm_order: ConfirmOrder,
        place_order: PlaceOrder,
        clock: FrozenClock,
    ) -> None:
        # Kafka delivers at least once, so a duplicated event must not corrupt
        # state. The state machine rejects the second confirmation loudly
        # instead of silently succeeding.
        from app.domain import InvalidOrderStateError

        placed = await place_order.execute(request_with(("SKU-001", 1, "10.00")))
        await confirm_order.execute(placed.order_id)
        clock.advance_to(LATER)
        with pytest.raises(InvalidOrderStateError):
            await confirm_order.execute(placed.order_id)


class TestCancelOrder:
    @pytest.mark.asyncio
    async def test_rejects_an_unknown_order(self, cancel_order: CancelOrder) -> None:
        from uuid import uuid4

        with pytest.raises(OrderNotFoundError):
            await cancel_order.execute(uuid4(), reason="does not exist")

    @pytest.mark.asyncio
    async def test_cancels_with_a_reason(
        self,
        cancel_order: CancelOrder,
        place_order: PlaceOrder,
        orders: InMemoryOrderRepository,
    ) -> None:
        placed = await place_order.execute(request_with(("SKU-001", 1, "10.00")))
        await cancel_order.execute(placed.order_id, reason="customer changed their mind")
        order = orders.orders[placed.order_id]
        assert order.status is OrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_compensates_a_confirmed_order(
        self,
        cancel_order: CancelOrder,
        confirm_order: ConfirmOrder,
        place_order: PlaceOrder,
        orders: InMemoryOrderRepository,
    ) -> None:
        # This is the compensating action of the saga: a confirmed order that
        # later fails downstream must be able to go back to cancelled.
        placed = await place_order.execute(request_with(("SKU-001", 1, "10.00")))
        await confirm_order.execute(placed.order_id)
        await cancel_order.execute(placed.order_id, reason="payment declined downstream")
        assert orders.orders[placed.order_id].status is OrderStatus.CANCELLED
