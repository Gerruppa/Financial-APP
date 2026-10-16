"""History of the whole Portfolio: its prices fetched into the cache, then computed from it and kept until the data
changes (issue #68, spec 6.1), on saved responses without the network."""

import asyncio
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.benchmarks import Benchmark, BenchmarkKind
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.prices import STOOQ
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.benchmarks import add_benchmark
from financial_app.persistence.db import init_db
from financial_app.persistence.history import history_prices
from financial_app.persistence.instruments import add_asset_class, add_instrument
from financial_app.persistence.settings import STOOQ_API_KEY, save_setting
from financial_app.persistence.transactions import add_transactions
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates
from financial_app.sources.portfolio_history import PortfolioHistory

STOOQ_FIXTURES = Path(__file__).parent / "fixtures" / "stooq"
TODAY = date(2026, 1, 10)


def _stooq(url: str) -> str:
    saved = STOOQ_FIXTURES / f"{url.split('s=', 1)[1].split('&', 1)[0]}.csv"
    return saved.read_text(encoding="utf-8") if saved.is_file() else "Brak danych"


def _portfolio(tmp_path: Path) -> tuple[Engine, int]:
    engine = init_db(tmp_path / "app.sqlite3")
    save_setting(engine, STOOQ_API_KEY, "KEY")
    account = add_account(engine, AccountDraft("IKE", "mBank", AccountType.REGULAR, ("PLN",))).id
    funds = add_asset_class(engine, "Fundusze indeksowe")
    wig = add_instrument(engine, InstrumentDraft("WIG", funds.id, "PLN", "GPW", source_symbols={STOOQ: "wig"})).id
    add_transactions(
        engine,
        [
            TransactionDraft(account, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(120000)),
            buy_or_sell(account, date(2026, 1, 2), TransactionType.BUY, wig, Decimal(1), Decimal(118000)),
        ],
    )
    return engine, account


def _history(engine: Engine, calls: list[int] | None = None) -> PortfolioHistory:
    async def counted(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
        if calls is not None:
            calls.append(1)
        return function(*args)

    quotes = QuoteHistory(engine, fetch=_stooq, today=lambda: TODAY, now=lambda: datetime(2026, 1, 10, 9))
    return PortfolioHistory(engine, quotes, NbpRates(engine, today=lambda: TODAY), lambda: TODAY, counted)


def test_after_a_fetch_each_day_is_valued_at_the_cached_closes(tmp_path: Path) -> None:
    engine, account = _portfolio(tmp_path)
    history = _history(engine)
    steps: list[tuple[int, int]] = []

    assert history.fetch(lambda done, total: steps.append((done, total))).instruments == {}
    values = asyncio.run(history.values())

    assert steps == [(1, 1)]
    assert [value.day.day for value in values] == list(range(2, 11))
    # 2000 PLN left in cash, the unit at the close of 9 January carried to 10 January
    assert values[-1].accounts == {account: Decimal("2000") + Decimal("119874.01")}
    assert values[-1].net_deposits == Decimal(120000)


def test_history_is_computed_once_until_invalidated(tmp_path: Path) -> None:
    engine, _ = _portfolio(tmp_path)
    calls: list[int] = []
    history = _history(engine, calls)

    asyncio.run(history.values())
    asyncio.run(history.values())
    history.invalidate()
    asyncio.run(history.values())

    assert len(calls) == 2


def test_an_empty_portfolio_has_no_history(tmp_path: Path) -> None:
    history = _history(init_db(tmp_path / "app.sqlite3"))

    assert asyncio.run(history.values()) == []


def test_a_computation_overtaken_by_an_invalidation_is_not_kept(tmp_path: Path) -> None:
    engine, _ = _portfolio(tmp_path)
    calls: list[int] = []
    history = _history(engine)

    async def slow(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
        calls.append(1)
        await asyncio.sleep(0)
        return function(*args)

    history.compute = slow

    async def overtaken() -> None:
        started = asyncio.ensure_future(history.values())
        await asyncio.sleep(0)
        history.invalidate()
        await started
        await history.values()

    asyncio.run(overtaken())

    assert len(calls) == 2


def test_a_benchmark_instruments_history_is_fetched_from_the_first_transaction(tmp_path: Path) -> None:
    # The Portfolio holds only cash; WIG is a benchmark (issue #91), so its closes are fetched too
    engine = init_db(tmp_path / "app.sqlite3")
    save_setting(engine, STOOQ_API_KEY, "KEY")
    account = add_account(engine, AccountDraft("IKE", "mBank", AccountType.REGULAR, ("PLN",))).id
    funds = add_asset_class(engine, "Fundusze indeksowe")
    wig = add_instrument(engine, InstrumentDraft("WIG", funds.id, "PLN", "GPW", source_symbols={STOOQ: "wig"})).id
    add_transactions(engine, [TransactionDraft(account, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(1000))])
    add_benchmark(engine, Benchmark(BenchmarkKind.INSTRUMENT, instrument_id=wig))
    steps: list[tuple[int, int]] = []

    _history(engine).fetch(lambda done, total: steps.append((done, total)))

    assert steps == [(1, 1)]
    assert [price.day for price in history_prices(engine, wig)][0] == date(2026, 1, 2)
