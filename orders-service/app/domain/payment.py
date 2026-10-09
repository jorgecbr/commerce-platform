"""Payment entity (payments bounded context).

Small on purpose: the point is to show that a second bounded context has its
own model and its own rules, instead of turning ``Order`` into a god object
with a ``payment_status`` column.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from app.domain.errors import InvalidOrderStateError
from app.domain.money import Money
from app.domain.order import OrderId
from app.domain.utc_datetime import UtcDatetime

PaymentId = UUID


class PaymentStatus(StrEnum):
    """Where a payment attempt stands with the bank."""

    PENDING = "pending"
    AUTHORIZED = "authorized"
    VOIDED = "voided"


TERMINAL_PAYMENT_STATUSES = frozenset({PaymentStatus.VOIDED})


@dataclass(slots=True)
class Payment:
    """The attempt to charge a customer for an order."""

    id: PaymentId
    order_id: OrderId
    amount: Money
    status: PaymentStatus = PaymentStatus.PENDING
    created_at: UtcDatetime | None = None
    authorized_at: UtcDatetime | None = None
    events: tuple[str, ...] = field(default=(), repr=False)

    @classmethod
    def create(
        cls,
        *,
        payment_id: PaymentId,
        order_id: OrderId,
        amount: Money,
        now: UtcDatetime,
    ) -> "Payment":
        """Start a payment attempt for an order."""
        return cls(
            id=payment_id,
            order_id=order_id,
            amount=amount,
            status=PaymentStatus.PENDING,
            created_at=now,
        )

    @property
    def is_authorized(self) -> bool:
        """Whether the funds are currently held."""
        return self.status is PaymentStatus.AUTHORIZED

    def authorize(self, *, now: UtcDatetime) -> None:
        """Reserve the funds; ``void`` is the compensation."""
        if self.status is not PaymentStatus.PENDING:
            raise InvalidOrderStateError(f"Cannot authorize a payment in state '{self.status}'")
        self.status = PaymentStatus.AUTHORIZED
        self.authorized_at = now

    def void(self) -> None:
        """Release previously authorized funds (the compensating action)."""
        if self.status is not PaymentStatus.AUTHORIZED:
            raise InvalidOrderStateError(f"Cannot void a payment in state '{self.status}'")
        self.status = PaymentStatus.VOIDED
