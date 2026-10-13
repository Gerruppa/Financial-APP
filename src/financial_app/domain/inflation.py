"""Inflation over a period and the real return (L-10, spec 3.4.1 and 6.1).

The GUS month-on-month CPI (previous month = 100) is spread evenly across the month's days, compounding day by day, as
the sheet's Benchmarki do: a period inflates by each covered month's index raised to the share of its days covered.
As in the sheet, a month GUS has not published yet adds no inflation; ``Inflation.complete`` says whether that happened.
The "from" day is the base, as for the TWR, so a period covers the days after it up to and including ``last``.
"""

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from financial_app.domain.bonds import CpiReading

# GUS indices are percent of the previous month
INDEX_BASE = Decimal(100)


@dataclass(frozen=True)
class Inflation:
    """The inflation over a period as a fraction; ``known_until`` is the last day of the latest month with a reading
    within it, and ``complete`` whether every month of the period had one."""

    rate: Decimal
    known_until: date
    complete: bool


def inflation(readings: Iterable[CpiReading], first: date, last: date) -> Inflation | None:
    """The inflation from the end of ``first`` to the end of ``last``; ``None`` when no published month falls within."""
    indices = {
        (reading.year, reading.month): reading.month_on_month
        for reading in readings
        if reading.month_on_month is not None
    }
    factor = Decimal(1)
    known_until: date | None = None
    complete = True
    start = first + timedelta(days=1)
    while start <= last:
        days_in_month = calendar.monthrange(start.year, start.month)[1]
        month_end = start.replace(day=days_in_month)
        end = min(month_end, last)
        index = indices.get((start.year, start.month))
        if index is None:
            complete = False
        else:
            factor *= (index / INDEX_BASE) ** (Decimal((end - start).days + 1) / days_in_month)
            known_until = month_end
        start = month_end + timedelta(days=1)
    if known_until is None:
        return None
    return Inflation(factor - 1, known_until, complete)


def real_return(nominal: Decimal, inflation_rate: Decimal) -> Decimal:
    """The return after inflation: (1 + nominal) / (1 + inflation) − 1, as fractions."""
    return (1 + nominal) / (1 + inflation_rate) - 1
