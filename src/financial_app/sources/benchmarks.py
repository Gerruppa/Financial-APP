"""Benchmarks against History (issue #91): each saved benchmark's daily growth from the local caches alone (the GUS CPI,
an Instrument's prices and NBP Rates fetched with History, an Account's History), then the comparison."""

from collections.abc import Sequence
from datetime import date

from sqlalchemy import Engine

from financial_app.domain.benchmarks import (
    Benchmark,
    BenchmarkKind,
    ComparisonRow,
    Growth,
    account_growth,
    compare,
    cpi_growth,
    price_growth,
)
from financial_app.domain.history import ONE_DAY
from financial_app.domain.portfolio_history import DayValue, pln_prices
from financial_app.domain.transactions import PLN
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.benchmarks import list_benchmarks
from financial_app.persistence.bond_data import load_cpi
from financial_app.persistence.history import history_prices, nbp_rates_between
from financial_app.persistence.instruments import list_instruments

# The NBP Rate of a day after a holiday is the one published before it
_RATE_LOOKBACK = 14 * ONE_DAY


def benchmark_comparison(
    engine: Engine, history: Sequence[DayValue], first: date, last: date, account_id: int | None
) -> list[ComparisonRow]:
    """The View Scope's Portfolio over the period, then each saved benchmark but the scope's own Account."""
    if not history:
        return []
    benchmarks = [
        b for b in list_benchmarks(engine) if b.kind is not BenchmarkKind.ACCOUNT or b.account_id != account_id
    ]
    return compare(history, first, last, account_id, _growths(engine, benchmarks, history))


def _growths(
    engine: Engine, benchmarks: Sequence[Benchmark], history: Sequence[DayValue]
) -> list[tuple[Benchmark, str, Growth]]:
    first, last = history[0].day, history[-1].day
    instruments = {instrument.id: instrument for instrument in list_instruments(engine)}
    accounts = {account.id: account.name for account in list_accounts(engine)}
    cpi = cpi_growth(load_cpi(engine))
    growths: list[tuple[Benchmark, str, Growth]] = []
    for benchmark in benchmarks:
        if benchmark.kind is BenchmarkKind.CPI:
            growths.append((benchmark, benchmark.label(""), cpi))
        elif benchmark.kind is BenchmarkKind.ACCOUNT:
            assert benchmark.account_id is not None  # checked on creation
            name = accounts.get(benchmark.account_id, "")
            growths.append((benchmark, benchmark.label(name), account_growth(history, benchmark.account_id)))
        else:
            assert benchmark.instrument_id is not None  # checked on creation
            instrument = instruments[benchmark.instrument_id]
            currency = instrument.quote_currency
            rates = (
                {} if currency == PLN else {currency: nbp_rates_between(engine, currency, first - _RATE_LOOKBACK, last)}
            )
            prices = pln_prices(instrument, history_prices(engine, instrument.id), rates, first, last)
            growths.append((benchmark, benchmark.label(instrument.name), price_growth(prices)))
    return growths
