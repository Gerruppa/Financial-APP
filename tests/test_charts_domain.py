"""The Dashboard charts' data from History and the Transactions (issue #73, spec section 5 and 6.1)."""

from datetime import date
from decimal import Decimal

from financial_app.domain.charts import (
    ClassShares,
    Grouping,
    ValuePoint,
    class_shares,
    dividends_by_year,
    profit_series,
    value_series,
    xirr_series,
)
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.transactions import TransactionDraft, TransactionType, dividend

IKE, XTB = 1, 2
PZU = 10
SHARES, CASH = "Akcje polskie", "Gotówka"


def _on(day: date, accounts: dict[int, tuple[str, str]], classes: dict[int, dict[str, str]] | None = None) -> DayValue:
    """History's ``day``: per Account its (value, Net Deposits), and optionally its value per class."""
    values = {account: Decimal(value) for account, (value, _) in accounts.items()}
    deposits = {account: Decimal(deposits) for account, (_, deposits) in accounts.items()}
    by_class = {
        account: {name: Decimal(value) for name, value in held.items()} for account, held in (classes or {}).items()
    }
    totals: dict[str, Decimal] = {}
    for held in by_class.values():
        for name, value in held.items():
            totals[name] = totals.get(name, Decimal(0)) + value
    return DayValue(
        day, values, totals, sum(deposits.values(), Decimal(0)), deposits, frozenset(), frozenset(), by_class
    )


def _day(day: int, month: int = 1) -> date:
    return date(2026, month, day)


HISTORY = [
    _on(_day(1), {IKE: ("1000", "1000"), XTB: ("500", "500")}),
    _on(_day(2), {IKE: ("1100", "1000"), XTB: ("450", "500")}),
    _on(_day(3), {IKE: ("2150", "2000"), XTB: ("400", "500")}),
]


def test_value_series_gives_the_scopes_value_and_net_deposits_on_each_day_of_the_period() -> None:
    assert value_series(HISTORY, _day(2), _day(3)) == [
        ValuePoint(_day(2), Decimal(1550), Decimal(1500)),
        ValuePoint(_day(3), Decimal(2550), Decimal(2500)),
    ]
    assert value_series(HISTORY, _day(1), _day(2), XTB) == [
        ValuePoint(_day(1), Decimal(500), Decimal(500)),
        ValuePoint(_day(2), Decimal(450), Decimal(500)),
    ]


def test_profit_is_value_less_net_deposits_as_in_the_sheet() -> None:
    assert profit_series(HISTORY, _day(2), _day(3), IKE) == [(_day(2), Decimal(100)), (_day(3), Decimal(150))]


def test_xirr_series_runs_from_the_periods_first_day_to_each_day() -> None:
    history = [
        _on(date(2025, 1, 1), {IKE: ("1000", "1000")}),
        _on(date(2025, 7, 2), {IKE: ("1050", "1000")}),
        _on(date(2026, 1, 1), {IKE: ("1100", "1000")}),
    ]

    series = xirr_series(history, date(2025, 1, 1), date(2026, 1, 1))

    assert [day for day, _ in series] == [date(2025, 1, 1), date(2025, 7, 2), date(2026, 1, 1)]
    assert series[0][1] is None
    assert series[2][1] == Decimal("0.1")


def test_xirr_series_samples_a_long_period_keeping_its_last_day() -> None:
    history = [_on(date(2025, 1, day), {IKE: ("1000", "1000")}) for day in range(1, 11)]

    series = xirr_series(history, date(2025, 1, 1), date(2025, 1, 10), points=4)

    assert [day.day for day, _ in series] == [1, 4, 7, 10]


def test_class_shares_take_the_last_day_of_each_month_in_the_period() -> None:
    history = [
        _on(_day(30), {IKE: ("1000", "1000")}, {IKE: {CASH: "1000"}}),
        _on(_day(31), {IKE: ("1000", "1000")}, {IKE: {CASH: "250", SHARES: "750"}}),
        _on(_day(1, 2), {IKE: ("1000", "1000")}, {IKE: {CASH: "500", SHARES: "500"}}),
    ]

    shares = class_shares(history, _day(30), _day(1, 2), None, Grouping.MONTH)

    assert shares == [
        ClassShares("01.2026", {CASH: Decimal("0.25"), SHARES: Decimal("0.75")}),
        ClassShares("02.2026", {CASH: Decimal("0.5"), SHARES: Decimal("0.5")}),
    ]


def test_class_shares_follow_the_account_scope_and_group_by_quarter_half_year_or_year() -> None:
    history = [
        _on(date(2025, 12, 31), {IKE: ("1", "1"), XTB: ("1", "1")}, {IKE: {SHARES: "100"}, XTB: {CASH: "100"}}),
        _on(date(2026, 3, 31), {IKE: ("1", "1"), XTB: ("1", "1")}, {IKE: {SHARES: "100"}, XTB: {CASH: "100"}}),
    ]

    def labels(grouping: Grouping) -> list[str]:
        return [share.label for share in class_shares(history, date(2025, 12, 31), date(2026, 3, 31), XTB, grouping)]

    assert class_shares(history, date(2026, 3, 31), date(2026, 3, 31), XTB, Grouping.YEAR) == [
        ClassShares("2026", {CASH: Decimal(1)})
    ]
    assert labels(Grouping.QUARTER) == ["IV kw. 2025", "I kw. 2026"]
    assert labels(Grouping.HALF_YEAR) == ["II półr. 2025", "I półr. 2026"]
    assert labels(Grouping.YEAR) == ["2025", "2026"]


def test_a_day_with_nothing_held_has_no_class_shares() -> None:
    history = [_on(_day(31), {IKE: ("0", "0")}, {IKE: {CASH: "0"}})]

    assert class_shares(history, _day(31), _day(31), None, Grouping.MONTH) == []


def _dividend(day: date, amount: str, account: int = IKE) -> TransactionDraft:
    return dividend(account, day, Decimal(amount), instrument_id=PZU)


def test_dividends_by_year_sum_each_accounts_net_dividends_in_the_period() -> None:
    transactions = [
        _dividend(date(2024, 6, 1), "10"),
        _dividend(date(2025, 6, 1), "20"),
        _dividend(date(2025, 7, 1), "5", XTB),
        _dividend(date(2026, 6, 1), "30"),
        TransactionDraft(IKE, date(2025, 6, 1), TransactionType.DEPOSIT, Decimal(1000)),
    ]

    assert dividends_by_year(transactions, date(2025, 1, 1), date(2026, 12, 31)) == {
        2025: {IKE: Decimal(20), XTB: Decimal(5)},
        2026: {IKE: Decimal(30)},
    }
    assert dividends_by_year(transactions, date(2025, 1, 1), date(2026, 12, 31), XTB) == {2025: {XTB: Decimal(5)}}
