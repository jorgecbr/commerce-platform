"""Domain errors.

Every rule this business enforces lives somewhere. When a rule is broken we
raise one of these, never a bare ``ValueError``. That distinction matters: an
adapter (HTTP, Kafka, database) can map a ``DomainError`` to a meaningful
response, and an unexpected ``ValueError`` means there is a bug in our code.
"""


class DomainError(Exception):
    """Base class for every business rule violation."""


# --- Value objects -------------------------------------------------------


class InvalidMoneyError(DomainError):
    """The amount or the currency is not a valid monetary value."""


class CurrencyMismatchError(DomainError):
    """Tried to combine amounts that are not in the same currency."""


class InvalidSkuError(DomainError):
    """The SKU does not follow the catalogue format."""


class InvalidUtcDatetimeError(DomainError):
    """A naive datetime was supplied where an aware UTC one is required."""


# --- Order ---------------------------------------------------------------


class EmptyOrderError(DomainError):
    """An order must contain at least one line."""


class TooManyLinesError(DomainError):
    """The order exceeds the maximum number of lines allowed."""


class DuplicateSkuError(DomainError):
    """The same SKU was added twice to the same order."""


class InvalidQuantityError(DomainError):
    """A line quantity is outside the allowed range."""


class NegativePriceError(DomainError):
    """A unit price cannot be negative."""


class InvalidOrderStateError(DomainError):
    """The requested transition is not allowed from the current state."""


class OrderNotFoundError(DomainError):
    """No order exists for the given identifier."""
