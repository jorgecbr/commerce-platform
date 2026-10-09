"""Money is the value object most likely to be reviewed, so it gets the most tests."""

from decimal import Decimal

import pytest

from app.domain import CurrencyMismatchError, InvalidMoneyError, Money
from app.domain.money import minor_unit_exponent


def usd(amount: int) -> Money:
    return Money(amount, "USD")


class TestValidation:
    def test_rejects_non_integer_amount(self) -> None:
        with pytest.raises(InvalidMoneyError):
            Money(10.5, "USD")  # type: ignore[arg-type]

    def test_rejects_bool_amount(self) -> None:
        # bool is a subclass of int; Money(True, "USD") must not silently be 1.
        with pytest.raises(InvalidMoneyError):
            Money(True, "USD")

    @pytest.mark.parametrize("currency", ["US", "USDD", "usd", "12A", ""])
    def test_rejects_invalid_currency(self, currency: str) -> None:
        with pytest.raises(InvalidMoneyError):
            Money(100, currency)

    def test_accepts_valid_currency(self) -> None:
        assert Money(100, "USD").currency == "USD"


class TestArithmetic:
    def test_adds_same_currency(self) -> None:
        assert (usd(1000) + usd(250)).amount == 1250

    def test_adds_exactly_no_float_error(self) -> None:
        # 0.1 + 0.2 != 0.3 with floats. With minor units it is exact.
        ten_cents = Money.from_decimal(Decimal("0.10"), "USD")
        twenty_cents = Money.from_decimal(Decimal("0.20"), "USD")
        assert (ten_cents + twenty_cents).amount == 30

    def test_refuses_to_mix_currencies(self) -> None:
        with pytest.raises(CurrencyMismatchError):
            usd(1000) + Money(1000, "EUR")

    def test_subtracts(self) -> None:
        assert (usd(1000) - usd(250)).amount == 750

    def test_multiplies_by_quantity(self) -> None:
        assert (usd(1050) * 3).amount == 3150

    def test_rejects_non_integer_factor(self) -> None:
        with pytest.raises(InvalidMoneyError):
            usd(1000) * 1.5  # type: ignore[operator]

    def test_rejects_bool_factor(self) -> None:
        with pytest.raises(InvalidMoneyError):
            usd(1000) * True

    def test_multiplication_is_commutative(self) -> None:
        assert (3 * usd(1050)) == usd(3150)

    def test_negates(self) -> None:
        assert (-usd(500)).amount == -500

    def test_is_immutable(self) -> None:
        original = usd(1000)
        _ = original + usd(500)
        assert original.amount == 1000

    def test_is_hashable_by_value(self) -> None:
        assert {usd(1000), usd(1000)} == {usd(1000)}


class TestFromDecimal:
    def test_converts_major_units_to_minor_units(self) -> None:
        assert Money.from_decimal(Decimal("12.34"), "USD").amount == 1234

    def test_rounds_half_up_not_bankers(self) -> None:
        # Banker's rounding would give 2 for 0.025 -> 0.02. Half-up gives 0.03.
        assert Money.from_decimal(Decimal("0.025"), "USD").amount == 3

    def test_handles_zero_decimal_currency(self) -> None:
        # JPY has no minor unit: 100 yen is stored as 100, not 10000.
        assert Money.from_decimal(Decimal("100"), "JPY").amount == 100

    def test_handles_three_decimal_currency(self) -> None:
        # KWD has three decimal places.
        assert Money.from_decimal(Decimal("1.234"), "KWD").amount == 1234

    def test_round_trip_through_as_decimal(self) -> None:
        original = Money.from_decimal(Decimal("99.99"), "EUR")
        assert Money.from_decimal(original.as_decimal(), "EUR") == original

    def test_unknown_currency_defaults_to_two_decimals(self) -> None:
        assert minor_unit_exponent("ZZZ") == 2
        assert Money.from_decimal(Decimal("1.00"), "ZZZ").amount == 100


class TestQueries:
    def test_zero_is_zero(self) -> None:
        assert Money.zero("USD").is_zero
        assert not Money.zero("USD").is_negative

    def test_negative_amount_is_negative(self) -> None:
        assert Money(-1, "USD").is_negative

    def test_str_is_human_readable(self) -> None:
        assert str(Money(1050, "USD")) == "10.50 USD"
