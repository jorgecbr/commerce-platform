"""Value objects and small entities: SKU, order line, timestamp, payment."""

from decimal import Decimal

import pytest

from app.domain import (
    InvalidOrderStateError,
    InvalidQuantityError,
    InvalidSkuError,
    InvalidUtcDatetimeError,
    Money,
    NegativePriceError,
    Payment,
    PaymentStatus,
    Sku,
    UtcDatetime,
)
from app.domain.order_line import MAX_QUANTITY_PER_LINE, OrderLine
from tests.conftest import FROZEN_NOW

ORDER_ID = "11111111-1111-1111-1111-111111111111"


class TestSku:
    def test_accepts_valid_sku(self) -> None:
        assert Sku("SKU-001").value == "SKU-001"

    @pytest.mark.parametrize("value", ["", "A", "AB", "-SKU", "SKU-", "sku-001", "SKU 001", "SKU_001"])
    def test_rejects_invalid_sku(self, value: str) -> None:
        with pytest.raises(InvalidSkuError):
            Sku(value)

    def test_is_immutable_and_hashable(self) -> None:
        assert len({Sku("SKU-001"), Sku("SKU-001")}) == 1


class TestUtcDatetime:
    def test_rejects_naive_datetime(self) -> None:
        from datetime import datetime

        with pytest.raises(InvalidUtcDatetimeError):
            UtcDatetime(datetime(2026, 3, 1, 10, 0))  # no tzinfo

    def test_now_is_aware(self) -> None:
        assert UtcDatetime.now().value.tzinfo is not None

    def test_iso_round_trip(self) -> None:
        parsed = UtcDatetime.from_iso("2026-03-01T10:00:00+00:00")
        assert parsed == FROZEN_NOW
        assert parsed.to_iso() == "2026-03-01T10:00:00+00:00"

    def test_str_matches_to_iso(self) -> None:
        assert str(FROZEN_NOW) == FROZEN_NOW.to_iso()


class TestOrderLine:
    def test_computes_line_total(self) -> None:
        line = OrderLine(sku=Sku("SKU-001"), quantity=3, unit_price=Money(1050, "USD"))
        assert line.line_total.amount == 3150

    @pytest.mark.parametrize("quantity", [0, -1, MAX_QUANTITY_PER_LINE + 1])
    def test_rejects_out_of_range_quantity(self, quantity: int) -> None:
        with pytest.raises(InvalidQuantityError):
            OrderLine(sku=Sku("SKU-001"), quantity=quantity, unit_price=Money(100, "USD"))

    def test_rejects_non_integer_quantity(self) -> None:
        with pytest.raises(InvalidQuantityError):
            OrderLine(sku=Sku("SKU-001"), quantity="2", unit_price=Money(100, "USD"))  # type: ignore[arg-type]

    def test_rejects_bool_quantity(self) -> None:
        with pytest.raises(InvalidQuantityError):
            OrderLine(sku=Sku("SKU-001"), quantity=True, unit_price=Money(100, "USD"))

    def test_rejects_negative_price(self) -> None:
        with pytest.raises(NegativePriceError):
            OrderLine(sku=Sku("SKU-001"), quantity=1, unit_price=Money(-1, "USD"))

    def test_accepts_a_free_line(self) -> None:
        line = OrderLine(sku=Sku("SKU-001"), quantity=1, unit_price=Money(0, "USD"))
        assert line.line_total.is_zero

    def test_price_is_frozen_at_order_time(self) -> None:
        # The unit price is a value, so re-pricing the catalogue later cannot
        # change what the customer agreed to pay.
        line = OrderLine(sku=Sku("SKU-001"), quantity=1, unit_price=Money(1000, "USD"))
        new_catalogue_price = Money(9999, "USD")
        assert line.unit_price != new_catalogue_price


class TestPayment:
    def _payment(self) -> Payment:
        return Payment.create(
            payment_id="22222222-2222-2222-2222-222222222222",  # type: ignore[arg-type]
            order_id=ORDER_ID,  # type: ignore[arg-type]
            amount=Money.from_decimal(Decimal("45.50"), "USD"),
            now=FROZEN_NOW,
        )

    def test_starts_pending(self) -> None:
        assert self._payment().status is PaymentStatus.PENDING

    def test_authorize_sets_the_timestamp(self) -> None:
        payment = self._payment()
        payment.authorize(now=FROZEN_NOW)
        assert payment.is_authorized
        assert payment.authorized_at == FROZEN_NOW

    def test_cannot_authorize_twice(self) -> None:
        payment = self._payment()
        payment.authorize(now=FROZEN_NOW)
        with pytest.raises(InvalidOrderStateError):
            payment.authorize(now=FROZEN_NOW)

    def test_void_releases_the_funds(self) -> None:
        payment = self._payment()
        payment.authorize(now=FROZEN_NOW)
        payment.void()
        assert payment.status is PaymentStatus.VOIDED

    def test_cannot_void_a_pending_payment(self) -> None:
        with pytest.raises(InvalidOrderStateError):
            self._payment().void()
