"""The value of a retail treasury bond by the MF issue letters (spec 3.4.1, L-3), so far for EDO.

One bond is valued, then multiplied by the quantity: its nominal compounds yearly at each year's rate, and within the
current year the interest accrues linearly over the days gone of the year's days; the bond is rounded to the grosz once,
as MF does (every matured EDO in the MF file pays exactly that). Each purchase earns from its own day, so a Bond
Series' price depends on its Lot's purchase day, and a Lot bought in a Rollover earns on the nominal like any other.

A rate MF has not published (nor the user corrected) is estimated as GUS CPI year on year of the month two months
before the year's anniversary, minus 100 and floored at 0 (deflation leaves the margin, as MF paid in 2015-16), plus the
Series' margin; while GUS has not published that month
the last reading forecasts it. Both are labelled, and so is a value resting on such a rate.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from functools import cached_property

from financial_app.domain.bonds import ISSUE_PRICE, TERM_MONTHS, BondSeries, BondType, CpiReading
from financial_app.domain.lots import Lot

# The bond types valued so far; any other Bond Series stays at cost until its slice (L-7, L-8)
VALUED_TYPES = frozenset({BondType.EDO})
# Months between a CPI reading and the anniversary whose rate it sets
CPI_LAG_MONTHS = 2
GROSZ = Decimal("0.01")


class RateLabel(StrEnum):
    """Shown beside a rate MF has not published yet, in Polish; an MF rate has none (spec 3.4.1)."""

    ESTIMATED_CPI = "szacowana (CPI)"  # from the CPI of the right month
    FORECAST_CPI = "prognoza (ostatnie CPI)"  # GUS has not published that month, so the last reading stands in


# The labels from the least to the most uncertain
_UNCERTAINTY = (None, RateLabel.ESTIMATED_CPI, RateLabel.FORECAST_CPI)


def most_uncertain(labels: Iterable[RateLabel | None]) -> RateLabel | None:
    """The most uncertain of ``labels``, ``None`` when every rate is published."""
    return max(labels, key=_UNCERTAINTY.index, default=None)


@dataclass(frozen=True)
class PeriodRate:
    """An interest period's rate (a fraction) and its label, ``None`` when MF published it or the user corrected it."""

    rate: Decimal
    label: RateLabel | None = None


@dataclass(frozen=True)
class BondValue:
    """One bond on a day: ``value`` its nominal with the interest so far, to the grosz; ``period`` the interest period
    it is in (from 1, the last one after maturity) and ``rate`` that period's rate; ``label`` the most uncertain label
    of the rates the value rests on."""

    value: Decimal
    period: int
    rate: PeriodRate
    label: RateLabel | None


class Cpi:
    """GUS CPI readings, year on year, by month."""

    def __init__(self, readings: Sequence[CpiReading]) -> None:
        known = sorted((r.year, r.month, r.year_on_year) for r in readings if r.year_on_year is not None)
        self.by_month = {(year, month): index for year, month, index in known}
        self.last = known[-1][2] if known else None

    def rate(self, year: int, month: int, margin: Decimal) -> PeriodRate | None:
        """The rate CPI of the month gives with ``margin``, else the last reading's forecast; ``None`` without CPI."""
        index = self.by_month.get((year, month))
        label = RateLabel.ESTIMATED_CPI
        if index is None:
            index, label = self.last, RateLabel.FORECAST_CPI
        if index is None:
            return None
        return PeriodRate(max(Decimal(0), (index - 100) / 100) + margin, label)


def bond_value(series: BondSeries, purchase_day: date, day: date, cpi: Cpi) -> BondValue | None:
    """One bond of ``series`` bought on ``purchase_day``, at the end of ``day`` (its nominal before the purchase).

    ``None`` for a type not valued yet, or without a rate it needs: the first year's from MF or the user, or no CPI at
    all for a later year MF has not published."""
    bond_type = series.bond_type
    if bond_type not in VALUED_TYPES:
        return None
    day = max(day, purchase_day)
    years = TERM_MONTHS[bond_type] // 12
    period = min(_years_between(purchase_day, day), years - 1)
    factor = Decimal(1)
    labels: list[RateLabel | None] = []
    rate: PeriodRate | None = None
    for year in range(period + 1):
        start, end = _anniversary(purchase_day, year), _anniversary(purchase_day, year + 1)
        rate = _rate(series, year, start, cpi)
        if rate is None:
            return None
        labels.append(rate.label)
        if year < period:
            factor *= 1 + rate.rate
        else:
            gone = min(day, end) - start
            factor *= 1 + rate.rate * gone.days / (end - start).days
    assert rate is not None
    value = (ISSUE_PRICE * factor).quantize(GROSZ, ROUND_HALF_UP)
    return BondValue(value, period + 1, rate, most_uncertain(labels))


def _rate(series: BondSeries, year: int, start: date, cpi: Cpi) -> PeriodRate | None:
    rates = series.rates
    published = rates[year] if year < len(rates) else None
    if published is not None:
        return PeriodRate(published)
    margin = series.margin
    if year == 0 or margin is None:
        return None
    months = start.year * 12 + start.month - 1 - CPI_LAG_MONTHS
    return cpi.rate(months // 12, months % 12 + 1, margin)


def _anniversary(purchase_day: date, years: int) -> date:
    """The day ``years`` after the purchase; 28 February for a purchase on 29 February in a common year."""
    year = purchase_day.year + years
    try:
        return purchase_day.replace(year=year)
    except ValueError:
        return date(year, 2, 28)


def _years_between(purchase_day: date, day: date) -> int:
    years = day.year - purchase_day.year
    return years - 1 if day < _anniversary(purchase_day, years) else years


@dataclass(frozen=True)
class BondPrice:
    """A Bond Series' price on ``day``: one bond's value depends on its Lot's purchase day."""

    series: BondSeries
    day: date
    cpi: Cpi

    def value(self, purchase_day: date) -> BondValue | None:
        return bond_value(self.series, purchase_day, self.day, self.cpi)

    def of(self, lot: Lot) -> Decimal:
        """One bond of ``lot`` in PLN; at its cost without a value."""
        value = self.value(lot.date)
        return lot.cost / lot.quantity if value is None else value.value


@dataclass(frozen=True)
class BondData:
    """What Bond Series are valued from: each Series by its Instrument id, and GUS CPI."""

    series: Mapping[int, BondSeries] = field(default_factory=dict)
    readings: Sequence[CpiReading] = ()

    @cached_property
    def cpi(self) -> Cpi:
        return Cpi(self.readings)

    def price(self, instrument_id: int, day: date) -> BondPrice | None:
        """The Series' price on ``day``; ``None`` for no Series, a type not valued yet or a Series without its first
        rate, which stay at cost."""
        series = self.series.get(instrument_id)
        if series is None or series.bond_type not in VALUED_TYPES or series.first_rate is None:
            return None
        return BondPrice(series, day, self.cpi)
