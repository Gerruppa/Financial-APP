"""The History engine: each day's value per Account and Asset Class and the Net Deposits (issue #68, spec 6.1)."""

from datetime import date
from decimal import Decimal

from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import Instrument
from financial_app.domain.portfolio_history import CASH_CLASS, FOREIGN_CASH_CLASS, HistoryPrice, daily_history
from financial_app.domain.transactions import (
    SplitRatio,
    TransactionDraft,
    TransactionType,
    buy_or_sell,
    cash_transfer,
    currency_exchange,
    security_transfer,
    split,
)

IKE, XTB = 1, 2
PZU, AAPL, EDO = 10, 20, 30
SHARES, FOREIGN, BONDS = "Akcje polskie", "Akcje zagraniczne", "Obligacje skarbowe polskie"


def _instrument(instrument_id: int, asset_class: str, currency: str = "PLN") -> Instrument:
    return Instrument("X", 1, currency, id=instrument_id, asset_class_name=asset_class, fallback_order=())


INSTRUMENTS = {
    PZU: _instrument(PZU, SHARES),
    AAPL: _instrument(AAPL, FOREIGN, "USD"),
    EDO: _instrument(EDO, BONDS),
}


def _day(day: int) -> date:
    return date(2026, 1, day)


def _deposit(amount: str, day: int = 1, account: int = IKE) -> TransactionDraft:
    return TransactionDraft(account, _day(day), TransactionType.DEPOSIT, Decimal(amount))


def _buy(quantity: str, price: str, day: int = 1, instrument: int = PZU, account: int = IKE) -> TransactionDraft:
    return buy_or_sell(account, _day(day), TransactionType.BUY, instrument, Decimal(quantity), Decimal(price))


def _price(day: int, price: str, currency: str = "PLN", adjusted_on: int | None = None) -> HistoryPrice:
    return HistoryPrice(_day(day), Decimal(price), currency, None if adjusted_on is None else _day(adjusted_on))


def _rate(day: int, rate: str) -> NbpRate:
    return NbpRate("USD", Decimal(rate), _day(day), f"{day}/A/NBP/2026")


def test_each_day_from_first_to_last_has_its_value_per_account_and_class() -> None:
    history = daily_history(
        [_deposit("1000"), _buy("10", "50", day=2)],
        INSTRUMENTS,
        {PZU: [_price(2, "50"), _price(3, "60")]},
        {},
        _day(1),
        _day(3),
    )

    assert [value.day for value in history] == [_day(1), _day(2), _day(3)]
    assert history[0].classes == {CASH_CLASS: Decimal(1000)}
    assert history[2].accounts == {IKE: Decimal(1100)}
    assert history[2].classes == {CASH_CLASS: Decimal(500), SHARES: Decimal(600)}
    assert history[2].total == Decimal(1100)


def test_a_day_without_a_quote_carries_the_last_one_forward() -> None:
    history = daily_history([_buy("10", "50")], INSTRUMENTS, {PZU: [_price(1, "55")]}, {}, _day(1), _day(4))

    assert history[3].classes[SHARES] == Decimal(550)
    assert history[3].unpriced == frozenset()


def test_without_any_quote_yet_a_position_is_valued_at_cost_and_flagged() -> None:
    history = daily_history([_buy("10", "50")], INSTRUMENTS, {PZU: [_price(2, "55")]}, {}, _day(1), _day(2))

    assert history[0].classes[SHARES] == Decimal(500)
    assert history[0].unpriced == {PZU}
    assert history[1].unpriced == frozenset()


def test_bond_series_are_valued_at_cost_until_stage_3() -> None:
    history = daily_history(
        [_buy("10", "100", instrument=EDO)], INSTRUMENTS, {EDO: [_price(1, "120")]}, {}, _day(1), _day(1)
    )

    assert history[0].classes[BONDS] == Decimal(1000)


def test_a_foreign_price_is_converted_at_the_nbp_rate_of_that_day() -> None:
    rate = NbpRate("USD", Decimal(4), _day(1), "1/A/NBP/2026")
    buy = buy_or_sell(IKE, _day(1), TransactionType.BUY, AAPL, Decimal(1), Decimal(100), nbp_rate=rate)
    history = daily_history(
        [buy],
        INSTRUMENTS,
        {AAPL: [_price(1, "100", "USD")]},
        {"USD": [_rate(1, "4"), _rate(2, "5")]},
        _day(1),
        _day(3),
    )

    assert [value.classes[FOREIGN] for value in history] == [Decimal(400), Decimal(500), Decimal(500)]


def test_foreign_cash_is_valued_at_the_nbp_rate_in_its_own_class() -> None:
    exchange = currency_exchange(IKE, _day(1), "USD", Decimal(100), Decimal(400))
    history = daily_history([exchange], INSTRUMENTS, {}, {"USD": [_rate(1, "4.5")]}, _day(1), _day(1))

    assert history[0].classes == {CASH_CLASS: Decimal(-400), FOREIGN_CASH_CLASS: Decimal(450)}


def test_a_split_adjusted_history_price_is_unadjusted_before_a_recorded_split() -> None:
    transactions = [_buy("10", "100", day=1), split(IKE, _day(3), PZU, SplitRatio(2, 1))]
    # Fetched on day 5, after the split: day 1's close is adjusted to half; the refresh's own day-2 Quote is not
    prices = [_price(1, "50", adjusted_on=5), _price(2, "110"), _price(4, "60", adjusted_on=5)]
    history = daily_history(transactions, INSTRUMENTS, {PZU: prices}, {}, _day(1), _day(4))

    assert [value.classes[SHARES] for value in history] == [Decimal(1000), Decimal(1100), Decimal(1100), Decimal(1200)]


def test_net_deposits_count_deposits_and_withdrawals_and_an_accounts_also_its_transfers() -> None:
    transactions = [
        _deposit("1000"),
        TransactionDraft(IKE, _day(2), TransactionType.WITHDRAWAL, Decimal(100)),
        _buy("10", "50", day=2),
        cash_transfer(IKE, _day(3), XTB, Decimal(200)),
        security_transfer(IKE, _day(3), XTB, PZU, Decimal(4)),
    ]
    history = daily_history(transactions, INSTRUMENTS, {PZU: [_price(3, "60")]}, {}, _day(1), _day(3))

    assert [value.net_deposits for value in history] == [Decimal(1000), Decimal(900), Decimal(900)]
    # The moved units at that day's price: 4 × 60
    assert history[2].account_net_deposits == {IKE: Decimal(460), XTB: Decimal(440)}
    assert history[2].accounts == {IKE: Decimal(560), XTB: Decimal(440)}


def test_a_security_transfer_without_a_price_moves_its_cost() -> None:
    transactions = [_buy("10", "50"), security_transfer(IKE, _day(2), XTB, PZU, Decimal(4))]
    history = daily_history(transactions, INSTRUMENTS, {}, {}, _day(1), _day(2))

    assert history[1].account_net_deposits == {IKE: Decimal(-200), XTB: Decimal(200)}


def test_foreign_cash_without_an_nbp_rate_yet_is_valued_at_cost_and_flagged() -> None:
    exchange = currency_exchange(IKE, _day(1), "USD", Decimal(100), Decimal(400))
    history = daily_history([exchange], INSTRUMENTS, {}, {"USD": [_rate(2, "4.5")]}, _day(1), _day(1))

    assert history[0].classes[FOREIGN_CASH_CLASS] == Decimal(400)
    assert history[0].unpriced_currencies == {"USD"}
