"""The broker's FX Conversion Fee on a foreign-currency Buy or Sell paid in PLN (issue #17, spec 3.3)."""

from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.currencies import NbpRate
from financial_app.domain.lots import open_positions
from financial_app.domain.transactions import (
    BrokerConversion,
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
)

XTB, APPLE = 1, 7
USD_RATE = NbpRate("USD", Decimal("3.6045"), date(2026, 1, 5), "002/A/NBP/2026")
HALF_PERCENT = Decimal("0.5")


def _converted(kind: TransactionType, charged: str, percent: Decimal = HALF_PERCENT) -> TransactionDraft:
    """10 × 150,50 USD with a 5 zł commission, converted by the broker for ``charged`` zł."""
    return buy_or_sell(
        XTB,
        date(2026, 1, 7),
        kind,
        APPLE,
        Decimal(10),
        Decimal("150.5"),
        Decimal(5),
        nbp_rate=USD_RATE,
        conversion=BrokerConversion(Decimal(charged), percent),
    )


def test_buy_costs_the_charged_amount_plus_the_commission() -> None:
    buy = _converted(TransactionType.BUY, "5451.90")

    assert buy.actual_amount == Decimal("5456.90")


def test_buy_derives_the_effective_rate_and_the_fee() -> None:
    buy = _converted(TransactionType.BUY, "5451.90")

    # The broker adds 0,5% to the market rate: 5451,90 / 1,005 = 5424,78 at market, so the fee is 27,12 zł
    assert buy.fx_conversion_fee == Decimal("27.12")
    assert buy.effective_fx_rate.quantize(Decimal("0.0001")) == Decimal("3.6225")  # 5451,90 / 1505 USD


def test_sell_derives_the_fee_from_the_market_value_above_the_charged_amount() -> None:
    sell = _converted(TransactionType.SELL, "5397.83")

    # The broker takes 0,5% off the market rate: 5397,83 / 0,995 = 5424,95 at market, so the fee is 27,12 zł
    assert sell.fx_conversion_fee == Decimal("27.12")
    assert sell.actual_amount == Decimal("5392.83")


def test_fee_is_a_deductible_cost_in_the_tax_amount() -> None:
    # 1505 USD × 3,6045 = 5424,77 zł at the NBP Rate
    assert _converted(TransactionType.BUY, "5451.90").tax_amount == Decimal("5456.89")  # + 5 + 27,12
    assert _converted(TransactionType.SELL, "5397.83").tax_amount == Decimal("5392.65")  # - 5 - 27,12


def test_fee_is_in_the_lot_cost() -> None:
    [position] = open_positions([_converted(TransactionType.BUY, "5451.90")])

    assert (position.cost, position.tax_cost) == (Decimal("5456.90"), Decimal("5456.89"))


def test_trade_without_a_conversion_has_no_fee() -> None:
    buy = buy_or_sell(XTB, date(2026, 1, 7), TransactionType.BUY, APPLE, Decimal(1), Decimal(100), nbp_rate=USD_RATE)

    assert buy.fx_conversion_fee is None


@pytest.mark.parametrize("charged", ["0", "-1", "100.001"])
def test_charged_amount_must_be_positive_to_the_grosz(charged: str) -> None:
    with pytest.raises(TransactionError, match="Kwota pobrana"):
        _converted(TransactionType.BUY, charged)


def test_conversion_needs_a_foreign_instrument() -> None:
    with pytest.raises(TransactionError, match="walucie obcej"):
        buy_or_sell(
            XTB,
            date(2026, 1, 7),
            TransactionType.BUY,
            APPLE,
            Decimal(1),
            Decimal(100),
            conversion=BrokerConversion(Decimal(100), HALF_PERCENT),
        )


def test_conversion_is_only_for_a_trade_paid_in_pln() -> None:
    with pytest.raises(TransactionError, match="w PLN"):
        buy_or_sell(
            XTB,
            date(2026, 1, 7),
            TransactionType.BUY,
            APPLE,
            Decimal(1),
            Decimal(100),
            nbp_rate=USD_RATE,
            cash_currency="USD",
            conversion=BrokerConversion(Decimal(362), HALF_PERCENT),
        )


def test_conversion_replaces_the_users_rate() -> None:
    with pytest.raises(TransactionError, match="kurs"):
        buy_or_sell(
            XTB,
            date(2026, 1, 7),
            TransactionType.BUY,
            APPLE,
            Decimal(1),
            Decimal(100),
            fx_rate=Decimal("3.6"),
            nbp_rate=USD_RATE,
            conversion=BrokerConversion(Decimal(362), HALF_PERCENT),
        )


def test_cash_transactions_carry_no_fee() -> None:
    with pytest.raises(TransactionError, match="nie dotyczy instrumentu"):
        TransactionDraft(
            XTB, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(1), fx_conversion_fee_percent=Decimal("0.5")
        )
