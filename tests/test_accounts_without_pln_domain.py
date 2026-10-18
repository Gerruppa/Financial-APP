"""Accounts without PLN (issue #124): a trade paid from foreign cash on such an Account has its commission in that
currency, taken from that cash and valued in PLN at the trade's rate (the Tax Amount at the NBP Rate)."""

from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.currencies import NbpRate
from financial_app.domain.lots import foreign_cash, open_positions
from financial_app.domain.transactions import (
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
    cash_balances,
    costs_by_account,
    deposit_or_withdrawal,
)

USD_ONLY = 1
APPLE = 10


def _usd_rate(rate: str = "4.00") -> NbpRate:
    return NbpRate("USD", Decimal(rate), date(2026, 1, 2), "001/A/NBP/2026")


def _usd_trade(
    kind: TransactionType, quantity: str, price: str, fee: str, *, day: int = 5, fx_rate: str | None = None
) -> TransactionDraft:
    return buy_or_sell(
        USD_ONLY,
        date(2026, 1, day),
        kind,
        APPLE,
        Decimal(quantity),
        Decimal(price),
        Decimal(fee),
        fx_rate=None if fx_rate is None else Decimal(fx_rate),
        nbp_rate=_usd_rate(),
        cash_currency="USD",
        commission_currency="USD",
    )


def test_buy_takes_its_usd_commission_from_the_dollars_and_nothing_from_pln() -> None:
    buy = _usd_trade(TransactionType.BUY, "10", "100", "2.50", fx_rate="3.90")

    assert buy.foreign_cash_change == Decimal("-1002.50")
    assert buy.cash_change == 0
    assert cash_balances([buy]) == {USD_ONLY: Decimal(0)}
    # 1000 USD and 2.50 USD of commission at the trade's rate of 3.90
    assert buy.actual_amount == Decimal("3909.75")
    assert buy.converted_amount == Decimal("3900.00")
    # At the NBP Rate of 4.00
    assert buy.tax_amount == Decimal("4010.00")
    [apple] = open_positions([buy])
    assert apple.cost == Decimal("3909.75")


def test_usd_commission_spends_usd_lots_at_its_pln_value() -> None:
    deposit = deposit_or_withdrawal(
        USD_ONLY,
        date(2026, 1, 2),
        TransactionType.DEPOSIT,
        Decimal(2000),
        cash_currency="USD",
        fx_rate=Decimal("3.80"),
        nbp_rate=_usd_rate(),
    )
    buy = _usd_trade(TransactionType.BUY, "10", "100", "2.50", fx_rate="3.90")

    [usd] = foreign_cash([deposit, buy])

    assert usd.quantity == Decimal("997.50")
    # 1002.50 USD bought at 3.80 went for 3909.75 zł
    assert usd.realized_result == Decimal("100.25")
    [lot] = usd.lots
    assert (lot.cost, lot.tax_cost) == (Decimal("3790.50"), Decimal("3990.00"))


def test_sell_brings_the_dollars_less_its_usd_commission_which_counts_in_costs_in_pln() -> None:
    sell = _usd_trade(TransactionType.SELL, "10", "110", "3")

    assert sell.foreign_cash_change == Decimal(1097)
    # At the NBP Rate of 4.00, as no rate of the user's was given
    assert sell.actual_amount == Decimal("4388.00")
    assert sell.commission_in_pln == Decimal("12.00")
    assert costs_by_account([sell]) == {USD_ONLY: Decimal("12.00")}


def test_usd_commission_counts_at_the_users_rate_in_costs_and_at_the_nbp_rate_in_the_tax_amount() -> None:
    sell = _usd_trade(TransactionType.SELL, "10", "110", "3", fx_rate="3.90")

    assert costs_by_account([sell]) == {USD_ONLY: Decimal("11.70")}
    assert sell.tax_amount == Decimal("4388.00")


def test_commission_is_in_pln_or_in_the_cash_the_trade_is_paid_from() -> None:
    with pytest.raises(TransactionError, match="w walucie płatności"):
        buy_or_sell(
            USD_ONLY,
            date(2026, 1, 5),
            TransactionType.BUY,
            APPLE,
            Decimal(1),
            Decimal(100),
            Decimal(1),
            nbp_rate=_usd_rate(),
            commission_currency="USD",
        )
