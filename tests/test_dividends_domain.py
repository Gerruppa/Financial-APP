"""Dividends and interest, Costs and DRIP (issue #18, spec 3.3, 3.5)."""

from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.currencies import NbpRate
from financial_app.domain.lots import InsufficientQuantityError, foreign_cash, open_positions
from financial_app.domain.transactions import (
    BrokerConversion,
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
    cash_balances,
    cost,
    costs_by_account,
    dividend,
    dividends_by_account,
    drip,
)

IKE, IBKR = 1, 2
PZU, APPLE = 10, 20
DAY = date(2026, 1, 7)
USD_RATE = NbpRate("USD", Decimal("3.6045"), date(2026, 1, 5), "002/A/NBP/2026")


def test_pln_dividend_adds_its_net_amount_to_cash_and_keeps_gross_and_tax_apart() -> None:
    payout = dividend(IKE, DAY, Decimal(100), Decimal(19), instrument_id=PZU)

    assert payout.transaction_type is TransactionType.DIVIDEND
    assert (payout.gross, payout.withholding_tax, payout.net) == (Decimal(100), Decimal(19), Decimal(81))
    assert payout.actual_amount == Decimal(81)
    assert cash_balances([payout]) == {IKE: Decimal(81)}


def test_interest_needs_no_instrument_nor_tax() -> None:
    interest = dividend(IKE, DAY, Decimal("12.34"))

    assert interest.instrument_id is None
    assert interest.withholding_tax == 0
    assert cash_balances([interest]) == {IKE: Decimal("12.34")}


def test_foreign_dividend_on_a_pln_account_is_converted_at_the_nbp_rate() -> None:
    payout = dividend(IKE, DAY, Decimal(10), Decimal("1.50"), instrument_id=APPLE, nbp_rate=USD_RATE)

    # 8,50 USD × 3,6045 = 30,638 zł
    assert payout.dividend_currency == "USD"
    assert payout.actual_amount == Decimal("30.64")
    assert payout.tax_amount == Decimal("30.64")
    assert cash_balances([payout]) == {IKE: Decimal("30.64")}


def test_foreign_dividend_converted_at_the_users_rate_keeps_the_tax_amount_at_the_nbp_rate() -> None:
    payout = dividend(
        IKE, DAY, Decimal(10), Decimal("1.50"), instrument_id=APPLE, fx_rate=Decimal("3.5"), nbp_rate=USD_RATE
    )

    assert payout.actual_amount == Decimal("29.75")
    assert payout.tax_amount == Decimal("30.64")


def test_foreign_dividend_into_foreign_cash_opens_a_foreign_cash_lot() -> None:
    payout = dividend(
        IBKR, DAY, Decimal(10), Decimal("1.50"), instrument_id=APPLE, nbp_rate=USD_RATE, cash_currency="USD"
    )

    assert cash_balances([payout]) == {IBKR: Decimal(0)}
    assert cash_balances([payout], currency="USD") == {IBKR: Decimal("8.50")}
    [usd] = foreign_cash([payout])
    assert (usd.quantity, usd.cost) == (Decimal("8.50"), Decimal("30.64"))


@pytest.mark.parametrize(
    ("gross", "tax", "message"),
    [
        ("0", "0", "brutto"),
        ("10", "-1", "Podatek"),
        ("10", "10", "Podatek"),
        ("10.005", "0", "grosza"),
        ("10", "1.005", "grosza"),
    ],
)
def test_dividend_needs_a_positive_gross_above_its_tax(gross: str, tax: str, message: str) -> None:
    with pytest.raises(TransactionError, match=message):
        dividend(IKE, DAY, Decimal(gross), Decimal(tax))


def test_foreign_dividend_into_foreign_cash_must_be_in_that_currency() -> None:
    with pytest.raises(TransactionError, match="EUR"):
        dividend(IBKR, DAY, Decimal(10), instrument_id=APPLE, nbp_rate=USD_RATE, cash_currency="EUR")


def test_dividend_carries_neither_a_price_nor_a_commission() -> None:
    with pytest.raises(TransactionError):
        TransactionDraft(
            IKE, DAY, TransactionType.DIVIDEND, Decimal(81), gross=Decimal(100), withholding_tax=Decimal(19),
            price=Decimal(1),
        )  # fmt: skip


def test_other_types_carry_no_gross_amount() -> None:
    with pytest.raises(TransactionError):
        TransactionDraft(IKE, DAY, TransactionType.DEPOSIT, Decimal(100), gross=Decimal(100))


def test_cost_takes_cash_and_adds_to_the_accounts_costs() -> None:
    fee = TransactionDraft(IKE, DAY, TransactionType.COST, Decimal(50))

    assert cash_balances([fee]) == {IKE: Decimal(-50)}
    assert costs_by_account([fee]) == {IKE: Decimal(50)}


def test_account_costs_also_sum_commissions_and_fx_conversion_fees() -> None:
    fee = TransactionDraft(IKE, DAY, TransactionType.COST, Decimal(50))
    buy = buy_or_sell(IKE, DAY, TransactionType.BUY, PZU, Decimal(10), Decimal(40), Decimal(5))
    converted = buy_or_sell(
        IBKR,
        DAY,
        TransactionType.BUY,
        APPLE,
        Decimal(10),
        Decimal("150.5"),
        Decimal(3),
        nbp_rate=USD_RATE,
        conversion=BrokerConversion(Decimal("5451.90"), Decimal("0.5")),
    )

    # 27,12 zł FX Conversion Fee on the converted Buy (see test_conversion_fee_domain)
    assert costs_by_account([fee, buy, converted]) == {IKE: Decimal(55), IBKR: Decimal("30.12")}


def test_drip_opens_a_lot_costing_the_reinvested_amount_without_moving_cash() -> None:
    reinvested = drip(IKE, DAY, PZU, Decimal("0.5"), Decimal(100), Decimal(19))

    assert reinvested.transaction_type is TransactionType.DRIP
    assert cash_balances([reinvested]) == {IKE: Decimal(0)}
    [position] = open_positions([reinvested])
    [lot] = position.lots
    assert (lot.date, lot.quantity, lot.cost, lot.tax_cost) == (DAY, Decimal("0.5"), Decimal(81), Decimal(81))


def test_foreign_drip_costs_the_net_dividend_at_the_nbp_rate() -> None:
    reinvested = drip(IKE, DAY, APPLE, Decimal("0.05"), Decimal(10), Decimal("1.50"), nbp_rate=USD_RATE)

    [lot] = open_positions([reinvested])[0].lots
    assert (lot.cost, lot.tax_cost) == (Decimal("30.64"), Decimal("30.64"))
    assert foreign_cash([reinvested]) == []


def test_drip_converts_nothing_so_it_takes_no_rate_of_its_own() -> None:
    with pytest.raises(TransactionError, match="kursie NBP"):
        TransactionDraft(
            IKE, DAY, TransactionType.DRIP, Decimal("29.75"), instrument_id=APPLE, quantity=Decimal(1),
            gross=Decimal("8.50"), fx_rate=Decimal("3.5"), nbp_rate=USD_RATE,
        )  # fmt: skip


def test_drip_needs_an_instrument_and_a_positive_quantity() -> None:
    with pytest.raises(TransactionError, match="Liczba"):
        drip(IKE, DAY, PZU, Decimal(0), Decimal(100))
    with pytest.raises(TransactionError, match="instrument"):
        TransactionDraft(
            IKE, DAY, TransactionType.DRIP, Decimal(100), quantity=Decimal(1), gross=Decimal(100)
        )  # fmt: skip


def test_drip_comes_after_a_sell_on_the_same_day() -> None:
    buy = buy_or_sell(IKE, date(2026, 1, 2), TransactionType.BUY, PZU, Decimal(1), Decimal(40))
    reinvested = drip(IKE, DAY, PZU, Decimal(1), Decimal(40))
    sell = buy_or_sell(IKE, DAY, TransactionType.SELL, PZU, Decimal(2), Decimal(45))

    with pytest.raises(InsufficientQuantityError):
        open_positions([buy, reinvested, sell])


def test_dividends_sum_and_reinvested_dividends_per_account() -> None:
    payout = dividend(IKE, DAY, Decimal(100), Decimal(19), instrument_id=PZU)
    reinvested = drip(IKE, DAY, PZU, Decimal("0.5"), Decimal(20))
    interest = dividend(IBKR, DAY, Decimal(5))

    assert dividends_by_account([payout, reinvested, interest]) == {IKE: Decimal(101), IBKR: Decimal(5)}


def _converted_dividend(**kwargs: object) -> TransactionDraft:
    """8,50 USD net (10 gross, 1,50 tax) credited by the broker as 30,49 zł after its 0,5% FX Conversion Fee."""
    return dividend(
        IKE, DAY, Decimal(10), Decimal("1.50"), instrument_id=APPLE, nbp_rate=USD_RATE,
        conversion=BrokerConversion(Decimal("30.49"), Decimal("0.5")), **kwargs,  # type: ignore[arg-type]
    )  # fmt: skip


def test_broker_converted_dividend_credits_the_amount_and_records_the_fee_as_a_cost() -> None:
    payout = _converted_dividend()

    # Credited 0,5% below the market rate: 30,49 / 0,995 = 30,64 zł at market, so the fee is 0,15 zł
    assert payout.actual_amount == Decimal("30.49")
    assert payout.fx_conversion_fee == Decimal("0.15")
    assert payout.effective_fx_rate.quantize(Decimal("0.0001")) == Decimal("3.5871")  # 30,49 / 8,50 USD
    assert payout.tax_amount == Decimal("30.64")
    assert cash_balances([payout]) == {IKE: Decimal("30.49")}
    assert costs_by_account([payout]) == {IKE: Decimal("0.15")}


def test_broker_conversion_needs_a_dividend_paid_into_pln() -> None:
    with pytest.raises(TransactionError, match="płatnej w PLN"):
        _converted_dividend(cash_currency="USD")


def test_foreign_cost_takes_foreign_cash_and_counts_at_the_nbp_rate() -> None:
    fee = cost(IBKR, DAY, Decimal(10), "Opłata", cash_currency="USD", nbp_rate=USD_RATE)

    assert fee.actual_amount == Decimal("36.05")  # 10 USD × 3,6045
    assert cash_balances([fee]) == {IBKR: Decimal(0)}
    assert cash_balances([fee], currency="USD") == {IBKR: Decimal(-10)}
    assert costs_by_account([fee]) == {IBKR: Decimal("36.05")}
    [usd] = foreign_cash([fee])
    assert (usd.quantity, usd.cost) == (Decimal(-10), Decimal("-36.05"))


def test_pln_cost_is_its_amount() -> None:
    assert cost(IKE, DAY, Decimal(50)) == TransactionDraft(IKE, DAY, TransactionType.COST, Decimal(50))


def test_foreign_cost_needs_the_nbp_rate_of_its_currency() -> None:
    with pytest.raises(TransactionError, match="kursu NBP"):
        cost(IBKR, DAY, Decimal(10), cash_currency="USD")
    with pytest.raises(TransactionError, match="kursu NBP"):
        cost(IBKR, DAY, Decimal(10), cash_currency="EUR", nbp_rate=USD_RATE)
