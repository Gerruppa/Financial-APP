"""The period selector shared by every chart and result (spec section 5 and 6.1).

A preset runs from its "from" day, where returns start, to today; a custom range from and to the days entered, never
past today. A period reaching before the first Transaction is clipped to it. The chosen period is remembered as text.
"""

import calendar
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class PeriodError(ValueError):
    """A custom range that cannot be used; the message is Polish."""


class PeriodPreset(StrEnum):
    ONE_MONTH = "1m"
    THREE_MONTHS = "3m"
    YEAR_TO_DATE = "ytd"
    ONE_YEAR = "1y"
    THREE_YEARS = "3y"
    FIVE_YEARS = "5y"
    SINCE_INCEPTION = "all"
    CUSTOM = "custom"

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    PeriodPreset.ONE_MONTH: "1M",
    PeriodPreset.THREE_MONTHS: "3M",
    PeriodPreset.YEAR_TO_DATE: "YTD",
    PeriodPreset.ONE_YEAR: "1R",
    PeriodPreset.THREE_YEARS: "3L",
    PeriodPreset.FIVE_YEARS: "5L",
    PeriodPreset.SINCE_INCEPTION: "Od początku",
    PeriodPreset.CUSTOM: "Własny",
}
# How many months before today each preset's "from" day lies
_MONTHS_BACK = {
    PeriodPreset.ONE_MONTH: 1,
    PeriodPreset.THREE_MONTHS: 3,
    PeriodPreset.ONE_YEAR: 12,
    PeriodPreset.THREE_YEARS: 36,
    PeriodPreset.FIVE_YEARS: 60,
}


@dataclass(frozen=True)
class Period:
    """A preset, or with ``CUSTOM`` the range from ``first`` to ``last``; raises ``PeriodError`` for a
    custom range without both days or ending before it starts."""

    preset: PeriodPreset
    first: date | None = None
    last: date | None = None

    def __post_init__(self) -> None:
        if self.preset is not PeriodPreset.CUSTOM:
            return
        if self.first is None or self.last is None:
            raise PeriodError("Podaj datę początkową i końcową okresu.")
        if self.last < self.first:
            raise PeriodError("Data początkowa okresu musi poprzedzać końcową.")


SINCE_INCEPTION = Period(PeriodPreset.SINCE_INCEPTION)


def period_dates(period: Period, today: date, inception: date | None) -> tuple[date, date]:
    """The period's "from" and "to" days; ``inception`` is the first Transaction's day, ``None`` without any."""
    last = today
    if period.preset is PeriodPreset.CUSTOM:
        assert period.first is not None and period.last is not None
        first, last = period.first, min(period.last, today)
    elif period.preset is PeriodPreset.YEAR_TO_DATE:
        first = date(today.year - 1, 12, 31)
    elif period.preset is PeriodPreset.SINCE_INCEPTION:
        first = inception or today
    else:
        first = months_before(today, _MONTHS_BACK[period.preset])
    if inception is not None:
        first = max(first, inception)
    return min(first, last), last


def period_setting(period: Period) -> str:
    """The text a period is remembered as, e.g. ``ytd`` or ``custom:2024-01-01:2024-06-30``."""
    if period.preset is PeriodPreset.CUSTOM:
        assert period.first is not None and period.last is not None
        return f"{period.preset}:{period.first.isoformat()}:{period.last.isoformat()}"
    return str(period.preset)


def parse_period(text: str | None) -> Period:
    """The remembered period; since inception when there is none or it cannot be read."""
    try:
        name, *days = (text or "").split(":")
        preset = PeriodPreset(name)
        if preset is PeriodPreset.CUSTOM:
            first, last = days
            return Period(preset, date.fromisoformat(first), date.fromisoformat(last))
        return Period(preset)
    except ValueError:
        return SINCE_INCEPTION


def months_before(day: date, months: int) -> date:
    """The same day ``months`` earlier, or that month's last day when it is shorter."""
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))
