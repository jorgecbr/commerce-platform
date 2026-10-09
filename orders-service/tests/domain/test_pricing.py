"""PricingService: volume discounts are business rules, so they are tested like one."""

from decimal import Decimal

import pytest

from app.domain import EmptyOrderError, Money, PricingService, Sku
from app.domain.order_line import OrderLine


def line(quantity: int, price: str = "10.00") -> OrderLine:
    return OrderLine(
        sku=Sku("SKU-001"),
        quantity=quantity,
        unit_price=Money.from_decimal(Decimal(price), "USD"),
    )


@pytest.fixture
def pricing() -> PricingService:
    return PricingService()


class TestDiscountRate:
    @pytest.mark.parametrize(
        ("quantity", "expected"),
        [(1, 0), (9, 0), (10, 5), (49, 5), (50, 10), (99, 10)],
    )
    def test_picks_the_best_tier(self, pricing: PricingService, quantity: int, expected: int) -> None:
        assert pricing.discount_rate_for(quantity) == expected


class TestDiscountedTotal:
    def test_no_discount_below_the_tier(self, pricing: PricingService) -> None:
        # 9 x 10.00 = 90.00, nothing to discount
        assert pricing.discounted_total(line(9)).amount == 9000

    def test_five_percent_at_ten_units(self, pricing: PricingService) -> None:
        # 10 x 10.00 = 100.00 -> 5% off -> 95.00
        assert pricing.discounted_total(line(10)).amount == 9500

    def test_ten_percent_at_fifty_units(self, pricing: PricingService) -> None:
        # 50 x 10.00 = 500.00 -> 10% off -> 450.00
        assert pricing.discounted_total(line(50)).amount == 45000

    def test_rounds_half_up_instead_of_truncating(self, pricing: PricingService) -> None:
        # 10 x 0.05 = 0.50 -> 5% = 0.025 -> half-up gives 0.03, so 0.47.
        # A plain `//` would give 0.02 and the customer would be undercharged
        # by a cent on every single order.
        assert pricing.discounted_total(line(10, "0.05")).amount == 47

    def test_discount_never_changes_the_currency(self, pricing: PricingService) -> None:
        assert pricing.discounted_total(line(10)).currency == "USD"


class TestOrderTotal:
    def test_sums_each_discounted_line(self, pricing: PricingService) -> None:
        total = pricing.order_total((line(10), line(1, "20.00")))
        assert total.amount == 9500 + 2000

    def test_rejects_empty_basket(self, pricing: PricingService) -> None:
        with pytest.raises(EmptyOrderError):
            pricing.order_total(())

    def test_is_pure(self, pricing: PricingService) -> None:
        first = pricing.order_total((line(10),))
        second = pricing.order_total((line(10),))
        assert first == second
