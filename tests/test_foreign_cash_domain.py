"""Foreign cash held as Lots, Currency Exchange and the FX result per Account (issue #16, spec 3.3, 3.5)."""

from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.currencies import NbpRate
from financial_app.domain.lots import foreign_cash, fx_result, open_positions
from financial_app.domain.transactions import (
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
    cash_balances,
    covering_exchange,
    currency_exchange,
)

IKE = 1
APPLE = 10


def test_exchange_from_pln_opens_a_foreign_cash_lot_with_its_pln_cost() -> None:
    exchange = currency_exchange(IKE, date(2026, 1, 7), "USD", Decimal(1000), Decimal("3650.00"))

    assert exchange.transaction_type is TransactionType.CURRENCY_EXCHANGE
    assert exchange.cash_change == Decimal("-3650.00")
    [usd] = foreign_cash([exchange])
    assert (usd.account_id, usd.currency, usd.quantity, usd.cost) == (IKE, "USD", Decimal(1000), Decimal("3650.00"))
    [lot] = usd.lots
    assert (lot.date, lot.quantity, lot.cost, lot.tax_cost) == (
        date(2026, 1, 7),
        Decimal(1000),
        Decimal("3650.00"),
        Decimal("3650.00"),
    )


def _usd_rate(rate: str = "3.80") -> NbpRate:
    return NbpRate("USD", Decimal(rate), date(2026, 1, 2), "001/A/NBP/2026")


def _usd_trade(
    kind: TransactionType, quantity: str, price: str, *, day: int, fee: str = "0", fx_rate: str | None = None
) -> TransactionDraft:
    return buy_or_sell(
        IKE,
        date(2026, 1, day),
        kind,
        APPLE,
        Decimal(quantity),
        Decimal(price),
        Decimal(fee),
        fx_rate=None if fx_rate is None else Decimal(fx_rate),
        nbp_rate=_usd_rate(),
        cash_currency="USD",
    )


def _exchange(foreign: str, pln: str, *, day: int, to_pln: bool = False) -> TransactionDraft:
    return currency_exchange(IKE, date(2026, 1, day), "USD", Decimal(foreign), Decimal(pln), to_pln=to_pln)


def test_buy_paid_in_usd_spends_the_oldest_usd_lots_and_realises_their_fx_result() -> None:
    exchanges = [_exchange("1000", "3600", day=1), _exchange("1000", "4000", day=2)]
    buy = _usd_trade(TransactionType.BUY, "10", "150", day=3, fee="5", fx_rate="3.80")

    [usd] = foreign_cash([*exchanges, buy])

    [lot] = usd.lots
    assert (lot.date, lot.quantity, lot.cost) == (date(2026, 1, 2), Decimal(500), Decimal(2000))
    # 1500 USD worth 5700 zł at the Buy's rate, which had cost 3600 + 500 × 4 zł
    assert usd.realized_result == Decimal(100)
    # The Apple Lot costs the dollars' value at the Buy's rate plus the PLN commission
    [apple] = open_positions([*exchanges, buy])
    assert apple.cost == Decimal("5705.00")
    assert buy.cash_change == Decimal(-5)
    assert buy.foreign_cash_change == Decimal(-1500)


def test_pln_commission_does_not_add_to_the_dollars_spent() -> None:
    buy = _usd_trade(TransactionType.BUY, "3", "33.333", day=3, fee="7.50")

    assert buy.foreign_cash_change == Decimal("-100.00")
    assert cash_balances([buy], currency="USD") == {IKE: Decimal("-100.00")}
    assert cash_balances([buy]) == {IKE: Decimal("-7.50")}


def test_sell_paid_into_usd_opens_a_usd_lot_at_its_value_before_the_commission() -> None:
    buy = _usd_trade(TransactionType.BUY, "10", "100", day=1)
    sell = _usd_trade(TransactionType.SELL, "10", "120", day=2, fee="5")

    [usd] = foreign_cash([buy, sell])

    # The Buy spent 1000 USD the Account did not have; the Sell's 1200 USD closes that and keeps 200 at 3.80 zł
    assert usd.quantity == Decimal(200)
    assert usd.cost == Decimal(760)
    assert usd.realized_result == Decimal(0)
    assert sell.cash_change == Decimal(-5)


def test_exchange_back_to_pln_realises_the_fx_result() -> None:
    usd_cash = foreign_cash([_exchange("1000", "3600", day=1), _exchange("400", "1700", day=5, to_pln=True)])

    [usd] = usd_cash
    assert (usd.quantity, usd.cost) == (Decimal(600), Decimal(2160))
    assert usd.realized_result == Decimal(260)


def test_spending_more_than_held_leaves_a_negative_lot_that_the_next_incoming_cash_closes() -> None:
    buy = _usd_trade(TransactionType.BUY, "10", "100", day=1, fx_rate="4.00")
    late_exchange = _exchange("1500", "5700", day=3)

    [short] = foreign_cash([buy])
    [usd] = foreign_cash([buy, late_exchange])

    assert (short.quantity, short.cost) == (Decimal(-1000), Decimal(-4000))
    # Dollars spent at 4,00 zł and bought later at 3,80 zł
    assert usd.realized_result == Decimal(200)
    assert (usd.quantity, usd.cost) == (Decimal(500), Decimal(1900))


def test_same_day_incoming_cash_comes_before_outgoing() -> None:
    buy = _usd_trade(TransactionType.BUY, "10", "100", day=1, fx_rate="3.70")
    exchange = _exchange("1000", "3650", day=1)

    [usd] = foreign_cash([buy, exchange])

    assert usd.lots == ()
    assert usd.realized_result == Decimal(50)


def test_unrealised_fx_result_at_a_rate() -> None:
    [usd] = foreign_cash([_exchange("1000", "3600", day=1)])

    assert usd.value(Decimal("3.75")) == Decimal(3750)
    assert usd.result(Decimal("3.75")) == Decimal(150)


def test_pln_only_transactions_have_no_foreign_cash() -> None:
    deposit = TransactionDraft(IKE, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(100))

    assert foreign_cash([deposit]) == []


@pytest.mark.parametrize(
    ("currency", "foreign", "message"),
    [
        ("PLN", "100", "Wybierz walutę obcą do wymiany."),
        ("usd", "100", "Wybierz walutę obcą do wymiany."),
        ("USD", "0", "Kwota w walucie musi być większa od zera."),
        ("USD", "1.001", "Kwotę w walucie podaj z dokładnością do setnych."),
    ],
)
def test_exchange_validation(currency: str, foreign: str, message: str) -> None:
    with pytest.raises(TransactionError, match=message):
        currency_exchange(IKE, date(2026, 1, 1), currency, Decimal(foreign), Decimal(400))


def test_usd_cash_pays_only_for_a_usd_instrument() -> None:
    with pytest.raises(TransactionError, match="tylko za instrument w USD"):
        buy_or_sell(IKE, date(2026, 1, 1), TransactionType.BUY, APPLE, Decimal(1), Decimal(10), cash_currency="USD")


def test_a_deposit_is_in_pln_only_for_now() -> None:
    with pytest.raises(TransactionError, match="tylko w PLN"):
        TransactionDraft(IKE, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(100), cash_currency="USD")


def test_fx_result_of_an_account_adds_realised_and_unrealised_results_of_each_currency() -> None:
    eur = currency_exchange(IKE, date(2026, 1, 1), "EUR", Decimal(100), Decimal(420))
    other_account = currency_exchange(2, date(2026, 1, 1), "USD", Decimal(100), Decimal(300))
    cash = foreign_cash(
        [_exchange("1000", "3600", day=1), _exchange("400", "1700", day=5, to_pln=True), eur, other_account]
    )

    # USD: 260 realised, 600 × (3,75 − 3,60) = 90 unrealised; EUR: 100 × (4,30 − 4,20) = 10
    assert fx_result(cash, IKE, {"USD": Decimal("3.75"), "EUR": Decimal("4.30")}) == Decimal(360)
    # Without a rate only the realised part counts
    assert fx_result(cash, IKE, {}) == Decimal(260)


def test_automatic_exchange_buys_exactly_the_dollars_the_buy_spends_not_its_pln_commission() -> None:
    buy = _usd_trade(TransactionType.BUY, "10", "150.5", day=3, fee="5", fx_rate="3.70")

    exchange = covering_exchange(buy)

    assert (exchange.date, exchange.cash_currency, exchange.to_pln) == (buy.date, "USD", False)
    assert exchange.quantity == Decimal("1505.00")
    assert exchange.actual_amount == Decimal("5568.50")
    assert exchange.comment == "Wymiana automatyczna"
    [usd] = foreign_cash([exchange, buy])
    assert (usd.lots, usd.realized_result) == ((), Decimal(0))
    assert cash_balances([exchange, buy]) == {IKE: Decimal("-5573.50")}


def test_automatic_exchange_at_the_nbp_rate_without_a_rate_of_its_own() -> None:
    buy = _usd_trade(TransactionType.BUY, "1", "100", day=3)

    assert covering_exchange(buy).actual_amount == Decimal("380.00")


def test_automatic_exchange_only_for_a_buy_paid_in_foreign_cash() -> None:
    sell = _usd_trade(TransactionType.SELL, "1", "100", day=3)

    with pytest.raises(TransactionError, match="tylko do zakupu"):
        covering_exchange(sell)
