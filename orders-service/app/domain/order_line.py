"""Order line entity.

An entity has identity of its own: two lines with the same product and price
are still different objects. In practice we key them by SKU, which is why a
duplicate SKU is rejected by the aggregate instead of silently merging.
"""

from dataclasses import dataclass

from app.domain.errors import InvalidQuantityError, NegativePriceError
from app.domain.money import Money
from app.domain.sku import Sku

MAX_QUANTITY_PER_LINE = 99


@dataclass(frozen=True, slots=True, order=True)
class OrderLine:
    """One product in an order, with the price agreed at purchase time."""

    sku: Sku
    quantity: int
    unit_price: Money

    def __post_init__(self) -> None:
        # See the note in money.py: the annotation is for mypy, this is the
        # runtime guarantee that untyped callers cannot sneak a string in.
        # Written bool-first on purpose so mypy does not flag it as redundant.
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise InvalidQuantityError(f"Quantity must be an int, got {type(self.quantity).__name__}")
        if not 1 <= self.quantity <= MAX_QUANTITY_PER_LINE:
            raise InvalidQuantityError(
                f"Quantity must be between 1 and {MAX_QUANTITY_PER_LINE}, got {self.quantity}"
            )
        if self.unit_price.is_negative:
            raise NegativePriceError(f"Unit price cannot be negative: {self.unit_price}")

    @property
    def line_total(self) -> Money:
        """Price of this line. The unit price is frozen at order time."""
        return self.unit_price * self.quantity
