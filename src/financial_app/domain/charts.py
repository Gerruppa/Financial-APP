"""The Dashboard charts' data (issue #73, spec section 5 and 6.1), for the View Scope and the period.

Each takes History (``portfolio_history.daily_history``) or the Transactions, the period's "from" and "to" days and the
scope: ``account_id`` ``None`` for the Total, or an Account. Like the sheet, the value and the profit (value less Net
Deposits) are the day's own, while XIRR runs from the "from" day, where returns start (as drawdown in
``metrics.drawdowns``). Shares are fractions, not percent.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from financial_app.domain.metrics import xirr_to_each
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.transactions import TransactionDraft

# How many days of a period the XIRR chart computes at most; each is a separate XIRR
XIRR_POINTS = 200


@dataclass(frozen=True)
class ValuePoint:
    """The scope's value and Net Deposits at the end of ``day``."""

    day: date
    value: Decimal
    net_deposits: Decimal


class Grouping(StrEnum):
    """How the Asset Class share chart groups History's days: by month, quarter, half-year or year."""

    MONTH = "month"
    QUARTER = "quarter"
    HALF_YEAR = "half-year"
    YEAR = "year"

    @property
    def label(self) -> str:
        return _GROUPING_LABELS[self]


_GROUPING_LABELS = {
    Grouping.MONTH: "Miesiąc",
    Grouping.QUARTER: "Kwartał",
    Grouping.HALF_YEAR: "Półrocze",
    Grouping.YEAR: "Rok",
}
_ROMAN = ("I", "II", "III", "IV")


@dataclass(frozen=True)
class ClassShares:
    """Each Asset Class's share of the scope's value on the last day of a month, quarter, half-year or year."""

    label: str
    shares: Mapping[str, Decimal]


def value_series(
    history: Sequence[DayValue], first: date, last: date, account_id: int | None = None
) -> list[ValuePoint]:
    """The value and Net Deposits on each day of the period."""
    return [_point(day, account_id) for day in _within(history, first, last)]


def profit_series(
    history: Sequence[DayValue], first: date, last: date, account_id: int | None = None
) -> list[tuple[date, Decimal]]:
    """The profit or loss on each day of the period: the value less Net Deposits, as the sheet's "Zysk / strata"."""
    return [(point.day, point.value - point.net_deposits) for point in value_series(history, first, last, account_id)]


def xirr_series(
    history: Sequence[DayValue], first: date, last: date, account_id: int | None = None, points: int = XIRR_POINTS
) -> list[tuple[date, Decimal | None]]:
    """XIRR from the "from" day to each day of the period (``None`` without a rate), at most ``points`` days evenly
    spaced back from the last one."""
    days = [day.day for day in _within(history, first, last)]
    step = max(1, math.ceil(len(days) / points))
    sampled = days[::-1][::step][::-1]
    return list(zip(sampled, xirr_to_each(history, first, sampled, account_id), strict=True))


def class_shares(
    history: Sequence[DayValue], first: date, last: date, account_id: int | None, grouping: Grouping
) -> list[ClassShares]:
    """The class shares on the last day of each group in the period; a day with nothing held is left out."""
    last_days: dict[str, DayValue] = {}
    for day in _within(history, first, last):
        last_days[_group_label(day.day, grouping)] = day
    shares = []
    for label, day in last_days.items():
        values = day.classes if account_id is None else day.account_classes.get(account_id, {})
        total = sum(values.values(), Decimal(0))
        if total:
            shares.append(ClassShares(label, {name: value / total for name, value in values.items() if value}))
    return shares


def dividends_by_year(
    transactions: Iterable[TransactionDraft], first: date, last: date, account_id: int | None = None
) -> dict[int, dict[int, Decimal]]:
    """Net Dividends and interest in PLN (their Actual Amounts) paid in the period, by year and Account id."""
    years: dict[int, dict[int, Decimal]] = {}
    for t in transactions:
        if t.transaction_type.is_dividend and first <= t.date <= last and account_id in (None, t.account_id):
            accounts = years.setdefault(t.date.year, {})
            accounts[t.account_id] = accounts.get(t.account_id, Decimal(0)) + t.actual_amount
    return dict(sorted(years.items()))


def _within(history: Sequence[DayValue], first: date, last: date) -> list[DayValue]:
    return [day for day in history if first <= day.day <= last]


def _point(day: DayValue, account_id: int | None) -> ValuePoint:
    if account_id is None:
        return ValuePoint(day.day, day.total, day.net_deposits)
    return ValuePoint(
        day.day,
        day.accounts.get(account_id, Decimal(0)),
        day.account_net_deposits.get(account_id, Decimal(0)),
    )


def _group_label(day: date, grouping: Grouping) -> str:
    if grouping is Grouping.MONTH:
        return f"{day.month:02d}.{day.year}"
    if grouping is Grouping.QUARTER:
        return f"{_ROMAN[(day.month - 1) // 3]} kw. {day.year}"
    if grouping is Grouping.HALF_YEAR:
        return f"{_ROMAN[(day.month - 1) // 6]} półr. {day.year}"
    return str(day.year)
