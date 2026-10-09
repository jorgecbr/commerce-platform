"""Use case: place a new order.

This is the boundary of a transaction. The orchestration order is the answer
to a question every interviewer asks: *in which order do you write to the
database and to the broker, and why?*

    1. build the aggregate (domain validates every invariant)
    2. store it
    3. buffer its domain events into the outbox  <- same transaction
    4. commit
    5. only then hand the events to the relay

Steps 2-4 happen atomically. If the process dies before step 5 the outbox row
is still in the database, so the event is not lost. Publishing to Kafka first
and writing to the database second would be the classic *dual write problem*.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.application.ports import Clock, EventPublisher, IdGenerator, OrderRepository, TransactionManager
from app.domain import Money, Order, OrderId, OrderLine, PricingService, Sku, UtcDatetime


@dataclass(frozen=True, slots=True, kw_only=True)
class PlaceOrderLineRequest:
    """One requested line, still in transport form (strings and decimals)."""

    sku: str
    quantity: int
    unit_price: Decimal
    currency: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PlaceOrderRequest:
    """A request to place an order, before any domain validation."""

    customer_id: str
    lines: tuple[PlaceOrderLineRequest, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class PlaceOrderResult:
    """What the caller gets back: identity, priced total and instant."""

    order_id: OrderId
    total: Money
    created_at: UtcDatetime


class PlaceOrder:
    """Create an order from a customer request."""

    def __init__(
        self,
        *,
        orders: OrderRepository,
        publisher: EventPublisher,
        clock: Clock,
        ids: IdGenerator,
        transactions: TransactionManager,
        pricing: PricingService,
    ) -> None:
        self._orders = orders
        self._publisher = publisher
        self._clock = clock
        self._ids = ids
        self._transactions = transactions
        self._pricing = pricing

    async def execute(self, request: PlaceOrderRequest) -> PlaceOrderResult:
        """Validate, persist and emit the events for a new order."""
        now = self._clock.now()

        # 1. Transport -> domain. This is the anti-corruption boundary: from
        #    here on nothing knows about Decimal, str or HTTP.
        lines = tuple(
            OrderLine(
                sku=Sku(line.sku),
                quantity=line.quantity,
                unit_price=Money.from_decimal(line.unit_price, line.currency),
            )
            for line in request.lines
        )

        # 2. Domain decides whether this is a valid order.
        order = Order.place(
            order_id=self._ids.new_order_id(),
            customer_id=request.customer_id,
            lines=lines,
            now=now,
        )

        # 3. Persist state + events in one transaction.
        await self._orders.add(order)
        await self._publisher.publish(order.pull_events())
        await self._transactions.commit()

        # 4. Business pricing for reporting, on top of the raw order total.
        priced = self._pricing.order_total(lines)

        return PlaceOrderResult(order_id=order.id, total=priced, created_at=now)
