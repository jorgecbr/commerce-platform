"""The Order aggregate root.

Everything that can change an order goes through this object, and this object
alone guarantees the invariants:

  * an order always has at least one line
  * an order never has more than ``MAX_LINES_PER_ORDER`` lines
  * the same SKU cannot appear twice (a customer cannot negotiate the price
    of a product line by line)
  * an order only moves through the states in ``ALLOWED_TRANSITIONS``
  * a discount never exceeds the amount it discounts, and never goes negative
  * every state change bumps ``version`` (optimistic locking) and appends a
    domain event

The aggregate is **mutable** (it has identity and changes over its life) while
value objects are immutable (they are defined by their attributes). Mixing
those two is a classic modelling mistake.

No framework, no database, no ORM annotations. If this file could not be unit
tested in isolation, the boundary is wrong.
"""

from dataclasses import dataclass, field
from uuid import UUID

from app.domain.errors import (
    DuplicateSkuError,
    EmptyOrderError,
    InvalidDiscountError,
    TooManyLinesError,
)
from app.domain.events import (
    OrderCancelled,
    OrderConfirmed,
    OrderDomainEvent,
    OrderLineSnapshot,
    OrderPlaced,
    OrderShipped,
)
from app.domain.money import Currency, Money
from app.domain.order_line import OrderLine
from app.domain.order_status import OrderStatus, ensure_transition_allowed
from app.domain.sku import Sku
from app.domain.utc_datetime import UtcDatetime

OrderId = UUID
MAX_LINES_PER_ORDER = 50


@dataclass(slots=True)
class Order:
    """Aggregate root for the ordering bounded context."""

    id: OrderId
    customer_id: str
    status: OrderStatus
    lines: tuple[OrderLine, ...]
    created_at: UtcDatetime
    updated_at: UtcDatetime
    # Field default instead of a call: dataclass defaults are evaluated once
    # at import time, and a mutable default would be shared across instances.
    discount: Money = field(default_factory=lambda: Money.zero("USD"))
    version: int = 1
    events: tuple[OrderDomainEvent, ...] = field(default=(), repr=False)

    # --- construction -----------------------------------------------------

    @classmethod
    def place(
        cls,
        *,
        order_id: OrderId,
        customer_id: str,
        lines: tuple[OrderLine, ...],
        now: UtcDatetime,
        discount: Money | None = None,
    ) -> "Order":
        """Create a new order, applying every invariant before returning.

        ``place`` instead of ``__init__`` so the only way to build a valid
        order is a factory that already validated it.

        The discount is computed by ``PricingService`` and handed in, then
        frozen here. Freezing it matters: the catalogue may be repriced later,
        and what the customer agreed to pay must not change underneath them.
        """
        if not lines:
            raise EmptyOrderError("An order must contain at least one line")
        if len(lines) > MAX_LINES_PER_ORDER:
            raise TooManyLinesError(f"An order cannot hold more than {MAX_LINES_PER_ORDER} lines")

        seen: set[Sku] = set()
        for line in lines:
            if line.sku in seen:
                raise DuplicateSkuError(f"SKU {line.sku} appears more than once in the order")
            seen.add(line.sku)

        currency = lines[0].unit_price.currency
        raw_total = sum((line.line_total for line in lines), start=Money.zero(currency))
        discount = Money.zero(currency) if discount is None else discount
        if discount.is_negative:
            raise InvalidDiscountError(f"Discount cannot be negative: {discount}")
        if discount.amount > raw_total.amount:
            raise InvalidDiscountError(f"Discount {discount} exceeds the order total {raw_total}")

        order = cls(
            id=order_id,
            customer_id=customer_id,
            status=OrderStatus.PENDING,
            lines=lines,
            created_at=now,
            updated_at=now,
            discount=discount,
            version=1,
        )
        total = order.total
        order.events = (
            OrderPlaced(
                order_id=order_id,
                customer_id=customer_id,
                total=total,
                lines=tuple(OrderLineSnapshot(sku=line.sku.value, quantity=line.quantity) for line in lines),
                occurred_at=now,
            ),
        )
        return order

    # --- queries ----------------------------------------------------------

    @property
    def currency(self) -> Currency:
        """Return the order currency, shared by every line."""
        return self.lines[0].unit_price.currency

    @property
    def gross_total(self) -> Money:
        """Sum of the line totals, before any discount."""
        return sum((line.line_total for line in self.lines), start=Money.zero(self.currency))

    @property
    def total(self) -> Money:
        """What the customer pays.

        Derived rather than stored, so it can never disagree with the lines.
        The lines and the discount are both frozen at placement time.
        """
        return self.gross_total - self.discount

    @property
    def is_modifiable(self) -> bool:
        """Once confirmed, the basket is frozen (it may already be invoiced)."""
        return self.status is OrderStatus.PENDING

    # --- transitions ------------------------------------------------------

    def confirm(self, *, now: UtcDatetime) -> None:
        """Confirm the order. Compensation for this action is ``cancel``."""
        ensure_transition_allowed(self.status, OrderStatus.CONFIRMED)
        self.status = OrderStatus.CONFIRMED
        self._touch(now)
        self.events = (*self.events, OrderConfirmed(order_id=self.id, occurred_at=now))

    def ship(self, *, now: UtcDatetime) -> None:
        """Mark the order as shipped. Terminal, no compensation possible."""
        ensure_transition_allowed(self.status, OrderStatus.SHIPPED)
        self.status = OrderStatus.SHIPPED
        self._touch(now)
        self.events = (*self.events, OrderShipped(order_id=self.id, occurred_at=now))

    def cancel(self, *, reason: str, now: UtcDatetime) -> None:
        """Cancel the order. Terminal: a cancelled order never comes back."""
        ensure_transition_allowed(self.status, OrderStatus.CANCELLED)
        self.status = OrderStatus.CANCELLED
        self._touch(now)
        self.events = (*self.events, OrderCancelled(order_id=self.id, reason=reason, occurred_at=now))

    # --- domain events ----------------------------------------------------

    def pull_events(self) -> tuple[OrderDomainEvent, ...]:
        """Return and clear the pending events.

        Called by the application layer right after loading or changing the
        aggregate, so the same event is never published twice.
        """
        pending, self.events = self.events, ()
        return pending

    # --- internals --------------------------------------------------------

    def _touch(self, now: UtcDatetime) -> None:
        self.updated_at = now
        self.version += 1
