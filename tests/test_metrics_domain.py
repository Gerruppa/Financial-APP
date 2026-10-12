"""Metrics on History: XIRR, TWR, drawdown and volatility per Total or Account and period (issue #69, spec 6.1)."""

from datetime import date
from decimal import Decimal

from financial_app.domain.instruments import Instrument
from financial_app.domain.metrics import MaxDrawdown, daily_change, drawdowns, max_drawdown, twr, volatility, xirr
from financial_app.domain.portfolio_history import DayValue, HistoryPrice, daily_history
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell, cash_transfer

IKE, XTB = 1, 2


def _day(day: int) -> date:
    return date(2026, 1, day)


def _on(day: date, value: str, deposits: str) -> DayValue:
    """One Account's value and Net Deposits at the end of ``day``."""
    return DayValue(day, {IKE: Decimal(value)}, {}, Decimal(deposits), {IKE: Decimal(deposits)}, frozenset())


def _history(*days: tuple[str, str]) -> list[DayValue]:
    """One Account's History from day 1: (value, Net Deposits) at the end of each day."""
    return [_on(_day(n), value, deposits) for n, (value, deposits) in enumerate(days, start=1)]


def test_twr_chains_daily_returns_with_flows_at_the_end_of_the_day() -> None:
    # Day 2: +10 %; day 3: 1000 deposited at its end, the rest +10 %
    history = _history(("1000", "1000"), ("1100", "1000"), ("2210", "2000"))

    assert twr(history, _day(1), _day(3)) == Decimal("0.21")


def test_a_period_starts_from_the_value_on_its_from_day_and_is_clipped_to_the_history() -> None:
    history = _history(("1000", "1000"), ("1100", "1000"), ("2210", "2000"))

    assert twr(history, _day(2), _day(3)) == Decimal("0.1")
    assert twr(history, date(2025, 12, 1), date(2026, 2, 1)) == Decimal("0.21")


def test_a_transfer_between_accounts_is_a_flow_of_each_account_but_not_of_the_total() -> None:
    # Day 2: IKE gains 10 % and moves 550 of its 1100 to XTB, which gains 10 % on day 3
    history = [
        DayValue(_day(1), {IKE: Decimal(1000)}, {}, Decimal(1000), {IKE: Decimal(1000)}, frozenset()),
        DayValue(
            _day(2),
            {IKE: Decimal(550), XTB: Decimal(550)},
            {},
            Decimal(1000),
            {IKE: Decimal(450), XTB: Decimal(550)},
            frozenset(),
        ),
        DayValue(
            _day(3),
            {IKE: Decimal(550), XTB: Decimal(605)},
            {},
            Decimal(1000),
            {IKE: Decimal(450), XTB: Decimal(550)},
            frozenset(),
        ),
    ]

    assert twr(history, _day(1), _day(3)) == Decimal("0.155")
    assert twr(history, _day(1), _day(3), IKE) == Decimal("0.1")
    assert twr(history, _day(1), _day(3), XTB) == Decimal("0.1")


def test_xirr_counts_deposits_as_paid_in_withdrawals_as_paid_out_and_the_last_value_as_withdrawn() -> None:
    # Excel's XIRR example: -10000, then 2750, 4250 and 3250 withdrawn and 2750 left, giving 37.34 %
    history = [
        _on(date(2008, 1, 1), "10000", "10000"),
        _on(date(2008, 3, 1), "8000", "7250"),
        _on(date(2008, 10, 30), "5000", "3000"),
        _on(date(2009, 2, 15), "2500", "-250"),
        _on(date(2009, 4, 1), "2750", "-250"),
    ]

    rate = xirr(history, date(2008, 1, 1), date(2009, 4, 1))

    assert rate is not None and round(rate, 6) == Decimal("0.373363")


def test_xirr_over_a_period_takes_the_value_on_its_from_day_as_paid_in() -> None:
    history = [
        _on(date(2026, 1, 1), "1000", "1000"),
        _on(date(2027, 1, 1), "2000", "1500"),
        _on(date(2028, 1, 1), "2200", "1500"),
    ]

    assert xirr(history, date(2027, 1, 1), date(2028, 1, 1)) == Decimal("0.1")


def test_xirr_has_no_rate_with_nothing_invested() -> None:
    history = [_on(_day(1), "0", "0"), _on(_day(2), "0", "0")]

    assert xirr(history, _day(1), _day(2)) is None
    assert xirr([], _day(1), _day(2)) is None


def test_drawdown_is_the_fall_of_the_twr_from_its_highest_point_so_far() -> None:
    # A deposit on day 4 changes the value but not the TWR
    history = _history(
        ("1000", "1000"), ("1200", "1000"), ("900", "1000"), ("1960", "2000"), ("2450", "2000"), ("2695", "2000")
    )

    assert [(day, round(depth, 10)) for day, depth in drawdowns(history, _day(1), _day(6))] == [
        (_day(1), Decimal(0)),
        (_day(2), Decimal(0)),
        (_day(3), Decimal("-0.25")),
        (_day(4), Decimal("-0.2")),
        (_day(5), Decimal(0)),
        (_day(6), Decimal(0)),
    ]
    assert max_drawdown(history, _day(1), _day(6)) == MaxDrawdown(Decimal("-0.25"), _day(2), _day(3), _day(5))


def test_a_drawdown_not_won_back_yet_has_no_recovery_day() -> None:
    history = _history(("1000", "1000"), ("800", "1000"), ("900", "1000"))

    assert max_drawdown(history, _day(1), _day(3)) == MaxDrawdown(Decimal("-0.2"), _day(1), _day(2), None)
    assert max_drawdown(history, _day(3), _day(3)) is None


def test_volatility_is_the_spread_of_weekday_returns_a_year() -> None:
    # Friday 2 January starts the History; the weekend's moves do not count; Monday to Thursday: +1 %, −1 %, +1 %, −1 %
    values = ["1000", "1050", "1000", "1010", "999.9", "1009.899", "999.80001"]
    history = [_on(date(2026, 1, 2 + n), value, "1000") for n, value in enumerate(values)]

    # The sample standard deviation of ±1 % four times, √(4 × 0.0001 / 3), times √252
    rate = volatility(history, date(2026, 1, 2), date(2026, 1, 8))

    assert rate is not None and round(rate, 6) == Decimal("0.183303")
    assert volatility(history, date(2026, 1, 2), date(2026, 1, 5)) is None


def test_metrics_follow_the_history_engine() -> None:
    pzu = 10
    instruments = {pzu: Instrument("PZU", 1, "PLN", id=pzu, asset_class_name="Akcje polskie", fallback_order=())}
    transactions = [
        TransactionDraft(IKE, _day(1), TransactionType.DEPOSIT, Decimal(1000)),
        buy_or_sell(IKE, _day(1), TransactionType.BUY, pzu, Decimal(10), Decimal(50)),
        TransactionDraft(IKE, _day(3), TransactionType.DEPOSIT, Decimal(1000)),
        cash_transfer(IKE, _day(3), XTB, Decimal(1500)),
    ]
    prices = {pzu: [HistoryPrice(_day(1), Decimal(50), "PLN"), HistoryPrice(_day(2), Decimal(55), "PLN")]}
    history = daily_history(transactions, instruments, prices, {}, _day(1), _day(3))

    # Day 2: the shares gain 50 on 1000; day 3 only moves cash
    assert twr(history, _day(1), _day(3)) == Decimal("0.05")
    assert twr(history, _day(1), _day(3), IKE) == Decimal("0.05")
    assert twr(history, _day(1), _day(3), XTB) == Decimal(0)


def test_xirr_has_no_rate_when_everything_is_paid_in_on_the_last_day_and_none_when_flat() -> None:
    history = _history(("100", "100"), ("100", "100"))

    assert xirr(history, _day(1), _day(1)) is None
    flat = xirr(history, _day(1), _day(2))

    assert flat == 0 and flat is not None and not flat.is_signed()


def test_daily_change_is_todays_value_less_yesterdays_and_todays_flows() -> None:
    # Day 3: 1000 deposited and the rest gained 110
    history = _history(("1000", "1000"), ("1100", "1000"), ("2210", "2000"))

    assert daily_change(history) == Decimal(110)
    assert daily_change(history, IKE) == Decimal(110)


def test_on_the_first_day_the_daily_change_is_the_value_less_the_deposits() -> None:
    assert daily_change(_history(("1010", "1000"))) == Decimal(10)
    assert daily_change([]) is None


def test_an_account_moving_cash_out_has_no_daily_change_from_the_transfer() -> None:
    history = [
        DayValue(_day(1), {IKE: Decimal(1000)}, {}, Decimal(1000), {IKE: Decimal(1000)}, frozenset()),
        DayValue(
            _day(2),
            {IKE: Decimal(450), XTB: Decimal(550)},
            {},
            Decimal(1000),
            {IKE: Decimal(450), XTB: Decimal(550)},
            frozenset(),
        ),
    ]

    assert daily_change(history) == 0
    assert daily_change(history, IKE) == 0
    assert daily_change(history, XTB) == 0
