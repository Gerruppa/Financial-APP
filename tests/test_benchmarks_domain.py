"""Benchmarks (issue #91, spec 6): every Deposit and Withdrawal of the View Scope invested into the benchmark on its
day, with an optional "+x pp a year", compared with the Portfolio over the period."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from financial_app.domain.benchmarks import (
    Benchmark,
    BenchmarkError,
    BenchmarkKind,
    account_growth,
    compare,
    cpi_growth,
    parse_offset,
    price_growth,
)
from financial_app.domain.bonds import CpiReading
from financial_app.domain.portfolio_history import DayValue

IKE, XTB = 1, 2
NBSP, MINUS = " ", "−"
D1 = date(2026, 1, 1)
CPI = Benchmark(BenchmarkKind.CPI)
WIG = Benchmark(BenchmarkKind.INSTRUMENT, instrument_id=10)


def _day(offset: int) -> date:
    return D1 + timedelta(days=offset)


def _history(values: list[tuple[str, str]], account_id: int = IKE) -> list[DayValue]:
    """A History of one Account: each day's (value, Net Deposits)."""
    return [
        DayValue(
            _day(n), {account_id: Decimal(value)}, {}, Decimal(deposits), {account_id: Decimal(deposits)}, frozenset()
        )
        for n, (value, deposits) in enumerate(values)
    ]


def _values(row_series: list[tuple[date, Decimal]]) -> list[Decimal]:
    return [value for _, value in row_series]


def test_every_flow_is_invested_on_its_day_at_the_benchmarks_price() -> None:
    history = _history([("1000", "1000"), ("1600", "1550"), ("1700", "1550")])
    growth = price_growth({_day(0): Decimal(100), _day(1): Decimal(110), _day(2): Decimal(121)})

    portfolio, wig = compare(history, _day(0), _day(2), None, [(WIG, "WIG", growth)])

    # 10 units on day 1, 5 more at 110 on day 2, 15 units at 121 on day 3
    assert _values(wig.series) == [Decimal(1000), Decimal(1650), Decimal(1815)]
    assert wig.value == Decimal(1815) and not wig.short_history
    assert portfolio.value == Decimal(1700) and portfolio.benchmark is None
    assert portfolio.difference is None
    assert wig.difference == Decimal(1700) - Decimal(1815)
    assert wig.difference_rate == (Decimal(1700) - Decimal(1815)) / Decimal(1815)
    assert wig.twr == Decimal("0.21")


def test_before_the_benchmark_has_a_price_the_money_waits_as_cash() -> None:
    history = _history([("1000", "1000"), ("1000", "1000"), ("1000", "1000")])
    growth = price_growth({_day(1): Decimal(110), _day(2): Decimal(121)})

    _, wig = compare(history, _day(0), _day(2), None, [(WIG, "WIG", growth)])

    assert _values(wig.series) == [Decimal(1000), Decimal(1000), Decimal(1100)]
    assert wig.short_history


def test_a_period_starts_the_benchmark_at_the_portfolios_value_on_the_from_day() -> None:
    history = _history([("1000", "1000"), ("1200", "1000"), ("1300", "1000")])
    growth = price_growth({_day(0): Decimal(100), _day(1): Decimal(100), _day(2): Decimal(110)})

    portfolio, wig = compare(history, _day(1), _day(2), None, [(WIG, "WIG", growth)])

    assert _values(portfolio.series) == [Decimal(1200), Decimal(1300)]
    assert _values(wig.series) == [Decimal(1200), Decimal(1320)]


def test_an_offset_adds_its_points_a_year() -> None:
    days = [("1000", "1000")] * 366
    history = _history(days)
    flat = cpi_growth([CpiReading(2026, month, None, Decimal(100)) for month in range(1, 13)])

    _, cpi_plus = compare(
        history, _day(0), _day(365), None, [(Benchmark(BenchmarkKind.CPI, offset=Decimal(3)), "", flat)]
    )

    assert cpi_plus.value == pytest.approx(Decimal(1030), abs=Decimal("0.0001"))


def test_cpi_spreads_each_months_index_over_its_days_and_an_unpublished_month_adds_nothing() -> None:
    growth = cpi_growth([CpiReading(2026, 1, None, Decimal("103.1"))])

    january = Decimal(1)
    for day in range(1, 32):
        factor = growth(date(2026, 1, day))
        assert factor is not None
        january *= factor
    assert january == pytest.approx(Decimal("1.031"), abs=Decimal("1e-20"))
    assert growth(date(2026, 2, 1)) == 1


def test_another_account_as_benchmark_grows_by_its_daily_returns() -> None:
    history = [
        DayValue(_day(0), {IKE: Decimal(1000)}, {}, Decimal(1000), {IKE: Decimal(1000)}, frozenset()),
        DayValue(
            _day(1),
            {IKE: Decimal(1000), XTB: Decimal(500)},
            {},
            Decimal(1500),
            {IKE: Decimal(1000), XTB: Decimal(500)},
            frozenset(),
        ),
        DayValue(
            _day(2),
            {IKE: Decimal(1000), XTB: Decimal(550)},
            {},
            Decimal(1500),
            {IKE: Decimal(1000), XTB: Decimal(500)},
            frozenset(),
        ),
    ]
    xtb = Benchmark(BenchmarkKind.ACCOUNT, account_id=XTB)

    _, row = compare(history, _day(0), _day(2), IKE, [(xtb, "XTB", account_growth(history, XTB))])

    # IKE's 1000 waits until XTB holds something, then earns its 10 %
    assert _values(row.series) == [Decimal(1000), Decimal(1000), Decimal(1100)]
    assert row.short_history


def test_a_withdrawal_takes_money_out_of_the_benchmark() -> None:
    history = _history([("1000", "1000"), ("600", "500")])
    growth = price_growth({_day(0): Decimal(100), _day(1): Decimal(120)})

    _, wig = compare(history, _day(0), _day(1), None, [(WIG, "WIG", growth)])

    assert _values(wig.series) == [Decimal(1000), Decimal(700)]


@pytest.mark.parametrize(
    ("text", "offset"), [("", Decimal(0)), ("3", Decimal(3)), ("2,5", Decimal("2.5")), ("-1", Decimal(-1))]
)
def test_the_offset_is_points_a_year(text: str, offset: Decimal) -> None:
    assert parse_offset(text) == offset


@pytest.mark.parametrize("text", ["abc", "100", "-100"])
def test_an_offset_out_of_range_is_refused(text: str) -> None:
    with pytest.raises(BenchmarkError):
        parse_offset(text)


def test_a_benchmark_names_what_its_kind_needs() -> None:
    with pytest.raises(BenchmarkError):
        Benchmark(BenchmarkKind.INSTRUMENT)
    with pytest.raises(BenchmarkError):
        Benchmark(BenchmarkKind.CPI, account_id=IKE)
    assert Benchmark(BenchmarkKind.CPI, offset=Decimal(3)).label("") == f"CPI + 3{NBSP}pp/rok"
    assert (
        Benchmark(BenchmarkKind.ACCOUNT, account_id=IKE, offset=Decimal("-1.5")).label("IKE")
        == f"Konto IKE {MINUS} 1,5{NBSP}pp/rok"
    )
    assert WIG.label("WIG") == "WIG"
