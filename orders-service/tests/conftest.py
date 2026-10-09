"""Shared test fixtures and in-memory fakes.

Two rules followed throughout the suite:

1. **No mocking of our own code.** A mock of ``OrderRepository`` would only
   assert that the use case calls the methods we told it to call. A fake with
   real behaviour (a dictionary) actually verifies the use case works.
2. **No I/O in unit tests.** Nothing here opens a socket or a database, which
   is what makes the whole suite run in milliseconds and lets the domain be
   tested before any infrastructure exists.
"""

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.domain import Money, Order, OrderDomainEvent, OrderId, OrderLine, Sku, UtcDatetime

FROZEN_NOW = UtcDatetime.from_iso("2026-03-01T10:00:00+00:00")
LATER = UtcDatetime.from_iso("2026-03-01T11:30:00+00:00")


class FrozenClock:
    """Deterministic time: the test decides what 'now' is."""

    def __init__(self, moment: UtcDatetime = FROZEN_NOW) -> None:
        self._moment = moment

    def now(self) -> UtcDatetime:
        return self._moment

    def advance_to(self, moment: UtcDatetime) -> None:
        self._moment = moment


class SequentialIdGenerator:
    """Predictable identifiers so assertions can hardcode them."""

    def __init__(self, first: UUID | None = None) -> None:
        self._next = first or UUID("11111111-1111-1111-1111-111111111111")

    def new_order_id(self) -> OrderId:
        value = self._next
        self._next = UUID(int=self._next.int + 1)
        return value


class InMemoryOrderRepository:
    """A real, if temporary, store: it enforces existence and version."""

    def __init__(self) -> None:
        self.orders: dict[OrderId, Order] = {}

    async def add(self, order: Order) -> None:
        self.orders[order.id] = order

    async def get_by_id(self, order_id: OrderId) -> Order | None:
        return self.orders.get(order_id)

    async def save(self, order: Order) -> None:
        self.orders[order.id] = order


class RecordingEventPublisher:
    """Captures published events so tests can assert on them."""

    def __init__(self) -> None:
        self.published: list[OrderDomainEvent] = []

    async def publish(self, events: Sequence[OrderDomainEvent]) -> None:
        self.published.extend(events)


class RecordingTransactionManager:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def build_line(sku: str = "SKU-001", quantity: int = 2, price: str = "10.00") -> OrderLine:
    return OrderLine(sku=Sku(sku), quantity=quantity, unit_price=Money.from_decimal(Decimal(price), "USD"))


def build_lines() -> tuple[OrderLine, ...]:
    return (
        build_line("SKU-001", quantity=2, price="10.00"),
        build_line("SKU-002", quantity=1, price="25.50"),
    )


@pytest.fixture
def now() -> UtcDatetime:
    return FROZEN_NOW


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def orders() -> InMemoryOrderRepository:
    return InMemoryOrderRepository()


@pytest.fixture
def publisher() -> RecordingEventPublisher:
    return RecordingEventPublisher()


@pytest.fixture
def transactions() -> RecordingTransactionManager:
    return RecordingTransactionManager()


@pytest.fixture
def ids() -> SequentialIdGenerator:
    return SequentialIdGenerator()


@pytest.fixture
def customer_id() -> str:
    return "customer-42"


def unique_id() -> UUID:
    return uuid4()
