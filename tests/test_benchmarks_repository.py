"""Saving Benchmarks (issue #91), seeding the sheet's defaults once, and comparing against History from the caches."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.benchmarks import DEFAULT_BENCHMARKS, Benchmark, BenchmarkError, BenchmarkKind
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.prices import STOOQ, YAHOO, Quote
from financial_app.persistence.accounts import add_account, delete_account
from financial_app.persistence.benchmarks import (
    add_benchmark,
    delete_benchmark,
    ensure_default_benchmarks,
    list_benchmarks,
    set_shown,
)
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import (
    add_instrument,
    delete_instrument,
    list_asset_classes,
    list_instruments,
)
from financial_app.persistence.quotes import save_quote
from financial_app.persistence.reset import clear_portfolio
from financial_app.sources.benchmarks import benchmark_comparison

D1 = date(2026, 1, 1)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _class_id(engine: Engine, name: str) -> int:
    return next(c.id for c in list_asset_classes(engine) if c.name == name)


def _instrument(engine: Engine, name: str = "WIG", currency: str = "PLN", **symbols: str) -> int:
    return add_instrument(engine, InstrumentDraft(name, _class_id(engine, "Inne"), currency, source_symbols=symbols)).id


def test_benchmarks_keep_the_order_they_were_added_in(engine: Engine) -> None:
    wig = _instrument(engine)
    add_benchmark(engine, Benchmark(BenchmarkKind.CPI, offset=Decimal(3)))
    added = add_benchmark(engine, Benchmark(BenchmarkKind.INSTRUMENT, instrument_id=wig, shown=False))

    assert added.id is not None
    assert list_benchmarks(engine) == [
        Benchmark(BenchmarkKind.CPI, offset=Decimal(3)),
        Benchmark(BenchmarkKind.INSTRUMENT, instrument_id=wig, shown=False),
    ]

    set_shown(engine, added.id, True)
    assert list_benchmarks(engine)[1].shown
    delete_benchmark(engine, added.id)
    assert len(list_benchmarks(engine)) == 1


def test_the_same_benchmark_twice_is_refused_but_another_offset_is_another(engine: Engine) -> None:
    add_benchmark(engine, Benchmark(BenchmarkKind.CPI))
    add_benchmark(engine, Benchmark(BenchmarkKind.CPI, offset=Decimal(3)))

    with pytest.raises(BenchmarkError, match="już jest"):
        add_benchmark(engine, Benchmark(BenchmarkKind.CPI, shown=False))


def test_the_defaults_are_seeded_once_creating_the_missing_instruments(engine: Engine) -> None:
    # CSPX is already in the catalog under another name: found by its Yahoo symbol
    cspx = _instrument(engine, "iShares S&P 500", "USD", **{YAHOO: "cspx.l"})

    assert ensure_default_benchmarks(engine)

    benchmarks = list_benchmarks(engine)
    assert benchmarks[0] == Benchmark(BenchmarkKind.CPI)
    by_id = {i.id: i for i in list_instruments(engine)}
    names = [by_id[b.instrument_id].name for b in benchmarks[1:] if b.instrument_id is not None]
    assert names == ["LON:ACWI", "iShares S&P 500", "AMS:V80A", "WSE:WIG", "WSE:SWIG80TR"]
    assert benchmarks[2].instrument_id == cspx
    wig = next(i for i in by_id.values() if i.name == "WSE:WIG")
    assert (wig.quote_currency, dict(wig.source_symbols)) == ("PLN", {STOOQ: "wig"})
    assert by_id[benchmarks[1].instrument_id or 0].quote_currency == "GBP"
    assert len(DEFAULT_BENCHMARKS) == 5

    # The user's list stays as they leave it
    for benchmark in benchmarks:
        assert benchmark.id is not None
        delete_benchmark(engine, benchmark.id)
    assert not ensure_default_benchmarks(engine)
    assert list_benchmarks(engine) == []


def test_deleting_an_instrument_or_account_drops_its_benchmarks(engine: Engine) -> None:
    wig = _instrument(engine)
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    add_benchmark(engine, Benchmark(BenchmarkKind.INSTRUMENT, instrument_id=wig))
    add_benchmark(engine, Benchmark(BenchmarkKind.ACCOUNT, account_id=ike))

    delete_instrument(engine, wig)
    delete_account(engine, ike)

    assert list_benchmarks(engine) == []


def test_clearing_the_data_brings_the_defaults_back(engine: Engine) -> None:
    ensure_default_benchmarks(engine)

    clear_portfolio(engine)

    assert list_benchmarks(engine) == []
    assert ensure_default_benchmarks(engine)
    assert len(list_benchmarks(engine)) == 6


def _history(values: list[str]) -> list[DayValue]:
    return [
        DayValue(D1 + timedelta(days=n), {1: Decimal(value)}, {}, Decimal(1000), {1: Decimal(1000)}, frozenset())
        for n, value in enumerate(values)
    ]


def test_an_instrument_benchmark_grows_with_its_cached_prices(engine: Engine) -> None:
    wig = _instrument(engine)
    for day, price in ((D1, "100"), (D1 + timedelta(days=2), "110")):
        save_quote(engine, wig, Quote(Decimal(price), "PLN", day, "stooq"), datetime(2026, 1, 5))
    add_benchmark(engine, Benchmark(BenchmarkKind.INSTRUMENT, instrument_id=wig))
    add_benchmark(engine, Benchmark(BenchmarkKind.CPI))
    history = _history(["1000", "1000", "1050"])

    portfolio, row, cpi = benchmark_comparison(engine, history, D1, D1 + timedelta(days=2), None)

    assert (portfolio.name, row.name, cpi.name) == ("Portfel", "WIG", "CPI")
    # The price carries forward on the second day
    assert [value for _, value in row.series] == [Decimal(1000), Decimal(1000), Decimal(1100)]
    assert row.difference == Decimal(-50)
    assert cpi.value == Decimal(1000)


def test_the_scopes_own_account_is_no_benchmark_of_itself(engine: Engine) -> None:
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    add_benchmark(engine, Benchmark(BenchmarkKind.ACCOUNT, account_id=ike))
    history = _history(["1000"])

    assert [row.name for row in benchmark_comparison(engine, history, D1, D1, ike)] == ["Portfel"]
    assert [row.name for row in benchmark_comparison(engine, history, D1, D1, None)] == ["Portfel", "Konto IKE"]
