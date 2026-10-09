"""Public API of the domain layer.

Importing from ``app.domain`` (the package) instead of the individual modules
keeps the surface small and makes refactoring an internal file a non-event for
the rest of the codebase.
"""

from app.domain.errors import (
    CurrencyMismatchError,
    DomainError,
    DuplicateSkuError,
    EmptyOrderError,
    InvalidMoneyError,
    InvalidOrderStateError,
    InvalidQuantityError,
    InvalidSkuError,
    InvalidUtcDatetimeError,
    NegativePriceError,
    OrderNotFoundError,
    TooManyLinesError,
)
from app.domain.events import (
    OrderCancelled,
    OrderConfirmed,
    OrderDomainEvent,
    OrderPlaced,
    OrderShipped,
)
from app.domain.money import Currency, Money
from app.domain.order import MAX_LINES_PER_ORDER, Order, OrderId
from app.domain.order_line import MAX_QUANTITY_PER_LINE, OrderLine
from app.domain.order_status import ALLOWED_TRANSITIONS, OrderStatus
from app.domain.payment import Payment, PaymentId, PaymentStatus
from app.domain.pricing import PricingService
from app.domain.sku import Sku
from app.domain.utc_datetime import UtcDatetime

__all__ = [
    "ALLOWED_TRANSITIONS",
    "MAX_LINES_PER_ORDER",
    "MAX_QUANTITY_PER_LINE",
    "Currency",
    "CurrencyMismatchError",
    "DomainError",
    "DuplicateSkuError",
    "EmptyOrderError",
    "InvalidMoneyError",
    "InvalidOrderStateError",
    "InvalidQuantityError",
    "InvalidSkuError",
    "InvalidUtcDatetimeError",
    "Money",
    "NegativePriceError",
    "Order",
    "OrderCancelled",
    "OrderConfirmed",
    "OrderDomainEvent",
    "OrderId",
    "OrderLine",
    "OrderNotFoundError",
    "OrderPlaced",
    "OrderShipped",
    "OrderStatus",
    "Payment",
    "PaymentId",
    "PaymentStatus",
    "PricingService",
    "Sku",
    "TooManyLinesError",
    "UtcDatetime",
]
