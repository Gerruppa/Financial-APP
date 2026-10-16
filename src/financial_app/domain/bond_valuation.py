"""The value of a retail treasury bond by the MF issue letters (spec 3.4.1, L-3, L-7, L-8), and the coupons COI, ROR
and DOR pay out.

One bond is valued, then multiplied by the quantity: its nominal compounds yearly at each year's rate (TOS at its one
fixed rate every year), and within the current year the interest accrues linearly over the days gone of the year's days;
the bond is rounded to the grosz once, as MF does (every matured EDO, ROS and TOS in the MF file pays exactly that). The
three-month OTS earns its yearly rate over its days out of 365, as every OTS in the MF file pays. Each purchase earns
from its own day, so a Bond Series' price depends on its Lot's purchase day, and a Lot bought in a Rollover earns on the
nominal like any other.

The coupon types do not compound: each period (a year for COI, a month for ROR and DOR) pays out its coupon, 100 x the
rate for the period's share of a year rounded to the grosz, as every coupon in the MF file is; within the period the
bond is worth its nominal plus the coupon accrued linearly over the period's days gone. The last coupon comes with the
nominal at maturity.

A rate MF has not published (nor the user corrected) is estimated as GUS CPI year on year of the month two months
before the year's anniversary, minus 100 and floored at 0 (deflation leaves the margin, as MF paid in 2015-16), plus the
Series' margin; while GUS has not published that month the last reading forecasts it. A ROR or DOR month's rate is the
NBP reference rate (floored at 0) in force ten business days before the first day of the calendar month the period
starts in, plus the margin, so every Lot of a Series gets the Series' rate for that month. All are labelled, and so is a
value resting on such a rate.
"""

from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from functools import cached_property

from financial_app.domain.bonds import (
    COUPON_TYPES,
    FIXED_RATE_TYPES,
    ISSUE_PRICE,
    MONTHLY_TYPES,
    PERIODS,
    TERM_MONTHS,
    BondSeries,
    BondType,
    CpiReading,
    ReferenceRate,
    add_months,
    maturity,
)
from financial_app.domain.formatting import format_percent
from financial_app.domain.lots import Lot

# The types running less than a year, which earn their rate over their days out of DAYS_A_YEAR
SHORT_TYPES = frozenset(bond_type for bond_type, months in TERM_MONTHS.items() if months < 12)
DAYS_A_YEAR = 365
# Months between a CPI reading and the anniversary whose rate it sets
CPI_LAG_MONTHS = 2
# Business days between the NBP reference rate a ROR or DOR month takes and the first day of its calendar month
NBP_LAG_BUSINESS_DAYS = 10
GROSZ = Decimal("0.01")


class RateLabel(StrEnum):
    """Shown beside a rate MF has not published yet, in Polish; an MF rate has none (spec 3.4.1)."""

    ESTIMATED_CPI = "szacowana (CPI)"  # from the CPI of the right month
    FORECAST_CPI = "prognoza (ostatnie CPI)"  # GUS has not published that month, so the last reading stands in
    ESTIMATED_NBP = "szacowana (NBP)"  # from the NBP reference rate in force on the right day
    FORECAST_NBP = "prognoza (ostatnia stopa NBP)"  # the saved rates end before that day, so the last one stands in


# The labels from the least to the most uncertain
_UNCERTAINTY = (
    None,
    RateLabel.ESTIMATED_CPI,
    RateLabel.ESTIMATED_NBP,
    RateLabel.FORECAST_CPI,
    RateLabel.FORECAST_NBP,
)


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
    it is in (from 1, the last one after maturity; a month when ``monthly``, else a year; ``None`` for a bond running
    less than a year) and ``rate`` that period's rate; ``label`` the most uncertain label of the rates the value rests
    on."""

    value: Decimal
    period: int | None
    rate: PeriodRate
    label: RateLabel | None
    monthly: bool = False


@dataclass(frozen=True)
class Coupon:
    """The interest one bond of a coupon type is paid on ``day`` for its ``period`` (from 1), at ``rate``, in PLN."""

    day: date
    period: int
    amount: Decimal
    rate: PeriodRate


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


class ReferenceRates:
    """The NBP reference rate history, which sets the ROR and DOR months MF has not published, as known up to
    ``known_until`` (the day it was fetched; ``None`` when unknown, taken as current)."""

    def __init__(self, rates: Sequence[ReferenceRate], known_until: date | None = None) -> None:
        ordered = sorted(rates, key=lambda rate: rate.valid_from)
        self.days = [rate.valid_from for rate in ordered]
        self.rates = [rate.rate for rate in ordered]
        self.known_until = known_until

    def rate(self, period_start: date, margin: Decimal) -> PeriodRate | None:
        """The rate of a month starting on ``period_start``: the reference rate in force ten business days before the
        first day of its calendar month, plus ``margin``, a forecast when the rates are known only up to an earlier
        day; ``None`` without a rate in force then."""
        fixed_on = _business_days_before(period_start.replace(day=1), NBP_LAG_BUSINESS_DAYS)
        index = bisect_right(self.days, fixed_on)
        if not index:
            return None
        known = self.known_until is None or fixed_on <= self.known_until
        label = RateLabel.ESTIMATED_NBP if known else RateLabel.FORECAST_NBP
        return PeriodRate(max(Decimal(0), self.rates[index - 1]) + margin, label)


NO_REFERENCE_RATES = ReferenceRates(())


def _business_days_before(day: date, count: int) -> date:
    """The weekday ``count`` weekdays before ``day``; holidays are not known, as for the price refresh."""
    while count:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            count -= 1
    return day


def bond_value(
    series: BondSeries, purchase_day: date, day: date, cpi: Cpi, reference: ReferenceRates = NO_REFERENCE_RATES
) -> BondValue | None:
    """One bond of ``series`` bought on ``purchase_day``, at the end of ``day`` (its nominal before the purchase).

    ``None`` without a rate it needs: the first period's from MF or the user, or no CPI (no NBP reference rate for ROR
    and DOR) at all for a later period MF has not published."""
    bond_type = series.bond_type
    day = max(day, purchase_day)
    if bond_type in SHORT_TYPES:
        return _short_bond_value(series, purchase_day, day)
    if bond_type in COUPON_TYPES:
        return _coupon_bond_value(series, purchase_day, day, cpi, reference)
    years = TERM_MONTHS[bond_type] // 12
    period = min(_periods_between(purchase_day, day, 12), years - 1)
    factor = Decimal(1)
    labels: list[RateLabel | None] = []
    rate: PeriodRate | None = None
    for year in range(period + 1):
        start, end = _anniversary(purchase_day, year), _anniversary(purchase_day, year + 1)
        rate = _rate(series, year, start, cpi, reference)
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


def _short_bond_value(series: BondSeries, purchase_day: date, day: date) -> BondValue | None:
    rate = series.first_rate
    if rate is None:
        return None
    gone = min(day, maturity(series.bond_type, purchase_day)) - purchase_day
    value = (ISSUE_PRICE * (1 + rate * gone.days / DAYS_A_YEAR)).quantize(GROSZ, ROUND_HALF_UP)
    return BondValue(value, None, PeriodRate(rate), None)


def _coupon_bond_value(
    series: BondSeries, purchase_day: date, day: date, cpi: Cpi, reference: ReferenceRates
) -> BondValue | None:
    """A coupon type: its nominal plus the coupon accrued in the period ``day`` is in, the earlier coupons paid out."""
    months = _period_months(series.bond_type)
    period = min(_periods_between(purchase_day, day, months), PERIODS[series.bond_type] - 1)
    start, end = add_months(purchase_day, months * period), add_months(purchase_day, months * (period + 1))
    rate = _rate(series, period, start, cpi, reference)
    if rate is None:
        return None
    gone = min(day, end) - start
    accrued = rate.rate * months / 12 * gone.days / (end - start).days
    value = (ISSUE_PRICE * (1 + accrued)).quantize(GROSZ, ROUND_HALF_UP)
    return BondValue(value, period + 1, rate, rate.label, monthly=months == 1)


def coupons(
    series: BondSeries, purchase_day: date, day: date, cpi: Cpi, reference: ReferenceRates
) -> tuple[Coupon, ...]:
    """The coupons one bond of ``series`` bought on ``purchase_day`` was paid by ``day``, oldest first: one at the end
    of each period but the last, whose interest comes with the nominal at maturity. None for a type without coupons;
    they stop at the first period without a rate."""
    bond_type = series.bond_type
    if bond_type not in COUPON_TYPES:
        return ()
    months = _period_months(bond_type)
    paid = []
    for period in range(1, PERIODS[bond_type]):
        start, paid_on = add_months(purchase_day, months * (period - 1)), add_months(purchase_day, months * period)
        if paid_on > day:
            break
        rate = _rate(series, period - 1, start, cpi, reference)
        if rate is None:
            break
        amount = (ISSUE_PRICE * rate.rate * months / 12).quantize(GROSZ, ROUND_HALF_UP)
        paid.append(Coupon(paid_on, period, amount, rate))
    return tuple(paid)


def _period_months(bond_type: BondType) -> int:
    return TERM_MONTHS[bond_type] // PERIODS[bond_type]


def _rate(series: BondSeries, period: int, start: date, cpi: Cpi, reference: ReferenceRates) -> PeriodRate | None:
    """The rate of ``period`` (from 0), which starts on ``start``: MF's or the user's, else estimated."""
    rates = series.rates
    # A fixed rate holds every year; a TOS has one period in the MF file
    index = 0 if series.bond_type in FIXED_RATE_TYPES else period
    published = rates[index] if index < len(rates) else None
    if published is not None:
        return PeriodRate(published)
    margin = series.margin
    if period == 0 or margin is None:
        return None
    if series.bond_type in MONTHLY_TYPES:
        return reference.rate(start, margin)
    months = start.year * 12 + start.month - 1 - CPI_LAG_MONTHS
    return cpi.rate(months // 12, months % 12 + 1, margin)


def rate_text(value: BondValue) -> str:
    """The rate of the period ``value`` is in, with its number when the bond runs a year or more: "5,35% · rok 2",
    "4,00% · miesiąc 3"."""
    return period_rate_text(value.rate.rate, value.period, monthly=value.monthly)


def period_rate_text(rate: Decimal, period: int | None, *, monthly: bool) -> str:
    """``rate`` (a fraction) with its ``period``, a month when ``monthly``, else a year; no period without one."""
    text = format_percent(rate * 100)
    if period is None:
        return text
    unit = "miesiąc" if monthly else "rok"
    return f"{text} · {unit} {period}"


def _anniversary(purchase_day: date, years: int) -> date:
    """The day ``years`` after the purchase; 28 February for a purchase on 29 February in a common year."""
    return add_months(purchase_day, 12 * years)


def next_anniversary(bond_type: BondType, purchase_day: date, day: date) -> date | None:
    """The first day after ``day`` a new interest period of a bond bought on ``purchase_day`` starts; ``None`` in the
    last period, which ends at maturity."""
    months = _period_months(bond_type)
    for period in range(1, PERIODS[bond_type]):
        start = add_months(purchase_day, months * period)
        if start > day:
            return start
    return None


def _periods_between(purchase_day: date, day: date, months: int) -> int:
    """The whole periods of ``months`` from ``purchase_day`` to ``day``."""
    periods = ((day.year - purchase_day.year) * 12 + day.month - purchase_day.month) // months
    return periods - 1 if day < add_months(purchase_day, months * periods) else periods


@dataclass(frozen=True)
class BondPrice:
    """A Bond Series' price on ``day``: one bond's value depends on its Lot's purchase day."""

    series: BondSeries
    day: date
    cpi: Cpi
    reference: ReferenceRates = NO_REFERENCE_RATES

    def value(self, purchase_day: date) -> BondValue | None:
        return bond_value(self.series, purchase_day, self.day, self.cpi, self.reference)

    def coupons(self, purchase_day: date) -> tuple[Coupon, ...]:
        """The coupons a bond bought on ``purchase_day`` was paid by the day."""
        return coupons(self.series, purchase_day, self.day, self.cpi, self.reference)

    def of(self, lot: Lot) -> Decimal:
        """One bond of ``lot`` in PLN; at its cost without a value."""
        value = self.value(lot.date)
        return lot.cost / lot.quantity if value is None else value.value


@dataclass(frozen=True)
class BondData:
    """What Bond Series are valued from: each Series by its Instrument id, GUS CPI and the NBP reference rate (known
    up to ``reference_known_until``, the day it was fetched)."""

    series: Mapping[int, BondSeries] = field(default_factory=dict)
    readings: Sequence[CpiReading] = ()
    reference_rates: Sequence[ReferenceRate] = ()
    reference_known_until: date | None = None

    @cached_property
    def cpi(self) -> Cpi:
        return Cpi(self.readings)

    @cached_property
    def reference(self) -> ReferenceRates:
        return ReferenceRates(self.reference_rates, self.reference_known_until)

    def price(self, instrument_id: int, day: date) -> BondPrice | None:
        """The Series' price on ``day``; ``None`` for no Series or a Series without its first rate, which stay at
        cost."""
        series = self.series.get(instrument_id)
        if series is None or series.first_rate is None:
            return None
        return BondPrice(series, day, self.cpi, self.reference)
