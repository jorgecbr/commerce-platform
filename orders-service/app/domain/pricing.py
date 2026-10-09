"""Pricing domain service.

A *domain service* is logic that belongs to the business but does not fit in
any single entity, and that needs no state. Volume discounts are the textbook
example: they read several lines at once but must stay pure so they can be
unit tested without any fixture.

Rules:
  * 10 or more units of a SKU  -> 5% off that line
  * 50 or more units of a SKU  -> 10% off that line (the best one wins)
  * discounts are rounded half-up to the minor unit, never silently truncated
"""

from dataclasses import dataclass

from app.domain.errors import EmptyOrderError
from app.domain.money import Money
from app.domain.order_line import OrderLine

VOLUME_TIERS: tuple[tuple[int, int], ...] = (
    (50, 10),  # >= 50 units -> 10% off
    (10, 5),  # >= 10 units -> 5% off
)


@dataclass(frozen=True, slots=True)
class PricingService:
    """Stateless calculator of discounts. Inject it, do not instantiate inline."""

    def discount_rate_for(self, quantity: int) -> int:
        """Return the best applicable discount as a whole percentage."""
        for min_quantity, rate in VOLUME_TIERS:
            if quantity >= min_quantity:
                return rate
        return 0

    def discounted_total(self, line: OrderLine) -> Money:
        """Return the total for a line after its volume discount."""
        rate = self.discount_rate_for(line.quantity)
        if rate == 0:
            return line.line_total

        # Work in integers: (amount * (100 - rate)) // 100 would truncate the
        # cent downwards, so we round half-up explicitly instead.
        total = line.line_total.amount
        discount = (total * rate + 50) // 100
        return Money(total - discount, line.unit_price.currency)

    def order_total(self, lines: tuple[OrderLine, ...]) -> Money:
        """Return the discounted total of a whole basket."""
        if not lines:
            raise EmptyOrderError("Cannot price an empty basket")
        total = Money.zero(lines[0].unit_price.currency)
        for line in lines:
            total = total + self.discounted_total(line)
        return total

    def order_discount(self, lines: tuple[OrderLine, ...]) -> Money:
        """Return how much a whole basket is discounted.

        Returned as a discount rather than a total so the caller hands it to
        the aggregate, which freezes it alongside the lines. That is what keeps
        a later catalogue reprice from changing an order that already exists.
        """
        if not lines:
            raise EmptyOrderError("Cannot price an empty basket")
        gross = Money.zero(lines[0].unit_price.currency)
        for line in lines:
            gross = gross + line.line_total
        return gross - self.order_total(lines)
