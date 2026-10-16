"""Benchmarks (issue #91, spec 6): what the View Scope's money would be worth had every Deposit and Withdrawal gone
into the benchmark instead, on its day, without fees or taxes, as the sheet's Benchmarki tab computes it.

A benchmark is CPI (the GUS month-on-month index spread evenly across the month's days, as ``domain.inflation``), a
catalog Instrument (its PLN price from History's cache, the NBP Rate of the day) or another Account (its daily TWR
returns, so its own Deposits do not count as growth), each with an optional offset of "+x pp a year" compounded daily.
Each is a daily growth factor: on a day the benchmark has none yet (an Instrument before its first price, an Account
before it held anything) the money waits as cash and the benchmark is marked as having a shorter history, as the
sheet's "*". Over a period the benchmark starts at the Portfolio's value on the "from" day, as XIRR does (spec 6.1);
a day's flow comes at its end.
"""

import calendar
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from financial_app.domain.bonds import CpiReading
from financial_app.domain.formatting import format_points, parse_number
from financial_app.domain.history import ONE_DAY
from financial_app.domain.inflation import INDEX_BASE
from financial_app.domain.metrics import ScopePeriod, daily_returns, scope_period, twr
from financial_app.domain.portfolio_history import DayValue

# A benchmark's growth on a day (1 for none); ``None`` while it has no data, so the money waits as cash
type Growth = Callable[[date], Decimal | None]

DAYS_A_YEAR = 365
# An offset is a yearly rate in percentage points; at or beyond 100 it stops meaning anything
OFFSET_LIMIT = Decimal(100)


class BenchmarkError(ValueError):
    """A benchmark that cannot be saved; the message is in Polish."""


class BenchmarkKind(StrEnum):
    CPI = "cpi"
    INSTRUMENT = "instrument"
    ACCOUNT = "account"


@dataclass(frozen=True)
class Benchmark:
    """CPI, an Instrument (``instrument_id``) or an Account (``account_id``), with ``offset`` pp a year added;
    ``shown`` on the chart. ``id`` is the saved benchmark's."""

    kind: BenchmarkKind
    instrument_id: int | None = None
    account_id: int | None = None
    offset: Decimal = Decimal(0)
    shown: bool = True
    id: int | None = field(default=None, kw_only=True, compare=False)

    def __post_init__(self) -> None:
        needs = {BenchmarkKind.INSTRUMENT: self.instrument_id, BenchmarkKind.ACCOUNT: self.account_id}
        if self.kind is BenchmarkKind.INSTRUMENT and (self.instrument_id is None or self.account_id is not None):
            raise BenchmarkError("Wybierz instrument benchmarku.")
        if self.kind is BenchmarkKind.ACCOUNT and (self.account_id is None or self.instrument_id is not None):
            raise BenchmarkError("Wybierz konto benchmarku.")
        if self.kind is BenchmarkKind.CPI and any(target is not None for target in needs.values()):
            raise BenchmarkError("CPI nie wskazuje instrumentu ani konta.")
        _check_offset(self.offset)

    def label(self, target: str) -> str:
        """The benchmark's name, given its Instrument's or Account's (``target``): "CPI + 3 pp/rok", "Konto IKE"."""
        name = {BenchmarkKind.CPI: "CPI", BenchmarkKind.ACCOUNT: f"Konto {target}"}.get(self.kind, target)
        if not self.offset:
            return name
        sign = "+" if self.offset > 0 else "\N{MINUS SIGN}"
        return f"{name} {sign} {format_points(abs(self.offset), exact=True)}/rok"

    def same_as(self, other: Benchmark) -> bool:
        """Whether both compare against the same thing with the same offset."""
        return (self.kind, self.instrument_id, self.account_id, self.offset) == (
            other.kind,
            other.instrument_id,
            other.account_id,
            other.offset,
        )


@dataclass(frozen=True)
class DefaultBenchmark:
    """One of the sheet's default benchmark Instruments, created in the catalog when missing: its name, quote
    currency and Asset Class, and its Yahoo or Stooq symbol (an index Yahoo does not give)."""

    name: str
    currency: str
    asset_class: str
    yahoo: str = ""
    stooq: str = ""


# The sheet's defaults besides CPI (spec 6): its Google Finance tickers as names
DEFAULT_BENCHMARKS = (
    DefaultBenchmark("LON:ACWI", "GBP", "Akcje zagraniczne", yahoo="ACWI.L"),
    DefaultBenchmark("LON:CSPX", "USD", "Akcje zagraniczne", yahoo="CSPX.L"),
    DefaultBenchmark("AMS:V80A", "EUR", "Akcje zagraniczne", yahoo="V80A.AS"),
    DefaultBenchmark("WSE:WIG", "PLN", "Akcje polskie", stooq="wig"),
    DefaultBenchmark("WSE:SWIG80TR", "PLN", "Akcje polskie", stooq="swig80tr"),
)


@dataclass(frozen=True)
class ComparisonRow:
    """The Portfolio (``benchmark`` ``None``) or a benchmark over the period: its value each day (``series``, the
    "from" day first) and on the last, the Portfolio's ``difference`` from it in PLN and as a fraction of it (none for
    the Portfolio), the ``twr`` over the period and whether it had no data on some days."""

    benchmark: Benchmark | None
    name: str
    series: list[tuple[date, Decimal]]
    twr: Decimal
    difference: Decimal | None = None
    difference_rate: Decimal | None = None
    short_history: bool = False

    @property
    def value(self) -> Decimal:
        return self.series[-1][1] if self.series else Decimal(0)


def parse_offset(text: str) -> Decimal:
    """The offset typed in pp a year, 0 when left empty; raises ``BenchmarkError`` unless a number within ±100."""
    if not text.strip():
        return Decimal(0)
    try:
        offset = parse_number(text)
    except ValueError:
        raise BenchmarkError("Dodatek musi być liczbą punktów procentowych rocznie.") from None
    _check_offset(offset)
    return offset


def _check_offset(offset: Decimal) -> None:
    if not -OFFSET_LIMIT < offset < OFFSET_LIMIT:
        raise BenchmarkError("Dodatek musi mieścić się między −100 a 100 pp rocznie.")


def cpi_growth(readings: Iterable[CpiReading]) -> Growth:
    """CPI's daily growth: the month's index (previous month = 100) to the power of one over its days; 1 in a month
    GUS has not published."""
    indices = {(r.year, r.month): r.month_on_month for r in readings if r.month_on_month is not None}

    def growth(day: date) -> Decimal:
        index = indices.get((day.year, day.month))
        if index is None:
            return Decimal(1)
        return (index / INDEX_BASE) ** (Decimal(1) / calendar.monthrange(day.year, day.month)[1])

    return growth


def price_growth(prices: Mapping[date, Decimal]) -> Growth:
    """An Instrument's daily growth from its PLN price each day (``portfolio_history.pln_prices``): the day's price
    over the day before's; 1 on its first day with a price; ``None`` before it."""

    def growth(day: date) -> Decimal | None:
        price = prices.get(day)
        if price is None:
            return None
        before = prices.get(day - ONE_DAY)
        return Decimal(1) if before is None else price / before

    return growth


def account_growth(history: Sequence[DayValue], account_id: int) -> Growth:
    """An Account's daily growth from its TWR returns: ``None`` before it first held anything, 1 on a day without a
    return."""
    days = scope_period(history, date.min, date.max, account_id)
    returns = dict(daily_returns(days))
    first = next((day.day for day in days.days if day.value), None)

    def growth(day: date) -> Decimal | None:
        if first is None or day < first:
            return None
        return 1 + returns.get(day, Decimal(0))

    return growth


def compare(
    history: Sequence[DayValue],
    first: date,
    last: date,
    account_id: int | None,
    benchmarks: Sequence[tuple[Benchmark, str, Growth]],
) -> list[ComparisonRow]:
    """The Portfolio of the View Scope (``account_id``, ``None`` for Total) over the period, then each benchmark,
    given with its name and growth."""
    period = scope_period(history, first, last, account_id)
    days = ([] if period.start is None else [period.start]) + period.days
    portfolio = ComparisonRow(
        None, "Portfel", [(day.day, day.value) for day in days], twr(history, first, last, account_id)
    )
    rows = [portfolio]
    for benchmark, name, growth in benchmarks:
        series, growth_index, short = _simulate(period, growth, benchmark.offset)
        value = series[-1][1] if series else Decimal(0)
        difference = portfolio.value - value
        rows.append(
            ComparisonRow(
                benchmark,
                name,
                series,
                growth_index - 1,
                difference,
                difference / value if value else None,
                short,
            )
        )
    return rows


def _simulate(period: ScopePeriod, growth: Growth, offset: Decimal) -> tuple[list[tuple[date, Decimal]], Decimal, bool]:
    """The benchmark's value each day, its growth over the period and whether money waited as cash on some day."""
    daily_offset = (1 + offset / 100) ** (Decimal(1) / DAYS_A_YEAR)
    value = period.start_value
    series = [] if period.start is None else [(period.start.day, value)]
    index = Decimal(1)
    short = period.start is not None and growth(period.start.day) is None
    for day in period.days:
        factor = growth(day.day)
        if factor is None:
            short = short or bool(value or day.flow)
        else:
            factor *= daily_offset
            value *= factor
            index *= factor
        value += day.flow
        series.append((day.day, value))
    return series, index, short
