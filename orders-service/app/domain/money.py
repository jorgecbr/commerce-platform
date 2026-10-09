"""Money value object.

Two decisions worth defending in a review:

1. **Amounts are integers in the minor unit** (cents), never floats. Adding
   0.1 + 0.2 in binary floating point gives 0.30000000000000004; that error is
   unacceptable in a ledger.
2. **The currency travels with the amount.** Two ``Money`` values can only be
   added if they agree, which turns a whole class of bugs into an exception
   raised at the point of the mistake.
"""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.domain.errors import CurrencyMismatchError, InvalidMoneyError

# Documented alias rather than a NewType on purpose. A NewType would demand
# `Currency("USD")` at every call site (including tests and literals), and in
# practice that friction pushes teams to delete it. The real guarantee that a
# currency is well formed comes from the validation in ``Money.__post_init__``.
type Currency = str

# ISO 4217 alphabetic code: exactly three uppercase letters.
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_SUBUNIT_EXPONENT: dict[str, int] = {
    "BHD": 3,
    "BIF": 0,
    "CLP": 0,
    "ISK": 0,
    "JOD": 3,
    "JPY": 0,
    "KRW": 0,
    "KWD": 3,
    "OMR": 3,
    "TND": 3,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "MXN": 2,
    "COP": 2,
    "ARS": 2,
    "CLP_DEFAULT": 2,
}


def minor_unit_exponent(currency: str) -> int:
    """Return the number of decimal places a currency uses (2 for most of them)."""
    return _SUBUNIT_EXPONENT.get(currency, _SUBUNIT_EXPONENT["USD"])


@dataclass(frozen=True, slots=True, order=True)
class Money:
    """An amount in the minor unit of a currency."""

    amount: int
    currency: Currency

    def __post_init__(self) -> None:
        # Dataclasses do not enforce types at runtime, so the annotation above
        # is a promise mypy checks and this is the one mypy cannot see.
        if not isinstance(self.amount, int) or isinstance(self.amount, bool):  # type: ignore[redundant-expr]
            raise InvalidMoneyError(f"Amount must be an int, got {type(self.amount).__name__}")
        if not _CURRENCY_PATTERN.match(self.currency):
            raise InvalidMoneyError(f"Invalid ISO 4217 currency code: {self.currency!r}")

    # --- constructors -----------------------------------------------------

    @classmethod
    def zero(cls, currency: str) -> "Money":
        """Return an additive identity in the given currency."""
        return cls(0, currency)

    @classmethod
    def from_decimal(cls, amount: Decimal, currency: str) -> "Money":
        """Build from a human amount (12.34) using half-up rounding.

        Half-up matches what a human expects on an invoice. Banker's rounding
        would round 0.005 to 0.00 and surprise the customer.
        """
        multiplier = Decimal(10) ** minor_unit_exponent(currency)
        return cls(int((amount * multiplier).quantize(Decimal(1), rounding=ROUND_HALF_UP)), currency)

    # --- queries ----------------------------------------------------------

    @property
    def is_zero(self) -> bool:
        """Whether this amount is exactly zero."""
        return self.amount == 0

    @property
    def is_negative(self) -> bool:
        """Whether this amount is below zero."""
        return self.amount < 0

    def as_decimal(self) -> Decimal:
        """Convert back to a human amount, using this currency's decimals."""
        quantum = Decimal(1).scaleb(-minor_unit_exponent(self.currency))
        return (Decimal(self.amount) * quantum).quantize(quantum)

    # --- arithmetic -------------------------------------------------------

    def _require_same_currency(self, other: "Money") -> None:
        """Raise unless both amounts share the same currency."""
        if self.currency != other.currency:
            raise CurrencyMismatchError(f"Cannot combine {self.currency} with {other.currency}")

    def __add__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: int) -> "Money":
        if not isinstance(factor, int) or isinstance(factor, bool):  # type: ignore[redundant-expr]
            raise InvalidMoneyError("Money can only be multiplied by an int")
        return Money(self.amount * factor, self.currency)

    __rmul__ = __mul__

    def __neg__(self) -> "Money":
        return Money(-self.amount, self.currency)

    def __str__(self) -> str:
        return f"{self.as_decimal()} {self.currency}"
