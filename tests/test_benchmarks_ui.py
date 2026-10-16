"""The Benchmarki tab (issue #91, spec 5 and 6): the View Scope's Portfolio against the sheet's default benchmarks and
the user's own, with History computed in the test from the cache alone."""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.benchmarks import Benchmark, BenchmarkKind
from financial_app.domain.bonds import CpiReading
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.transactions import TransactionDraft, TransactionType
from financial_app.persistence.accounts import add_account
from financial_app.persistence.benchmarks import add_benchmark, list_benchmarks
from financial_app.persistence.bond_data import save_cpi
from financial_app.persistence.db import init_db
from financial_app.persistence.settings import BENCHMARKS_SEEDED, save_setting
from financial_app.persistence.transactions import add_transactions
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates
from financial_app.sources.portfolio_history import PortfolioHistory
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
TODAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 9, 0)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """IKE: 1000 PLN in on 3.08; XTB: 3000 PLN in on 3.08; the CPI of August and September 1 % a month each."""
    engine = init_db(tmp_path / "app.sqlite3")
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    xtb = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id
    add_transactions(
        engine,
        [
            TransactionDraft(ike, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(1000)),
            TransactionDraft(xtb, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(3000)),
        ],
    )
    save_cpi(engine, [CpiReading(2026, 8, None, Decimal(101)), CpiReading(2026, 9, None, Decimal(101))])
    return engine


async def _inline(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
    return function(*args)


def _shell(engine: Engine) -> Callable[[], None]:
    quotes = QuoteHistory(engine, lambda url: "Brak danych", lambda: TODAY, lambda: NOW, lambda url: None)
    history = PortfolioHistory(engine, quotes, NbpRates(engine), lambda: TODAY, _inline)
    return lambda: build_shell(engine, now=lambda: NOW, history=history)


def _rows(user: User) -> list[list[str]]:
    rows = sorted(user.find(marker="benchmark-row").elements, key=lambda element: element.id)
    return [[d.text for d in row.descendants() if isinstance(d, ui.label)] for row in rows]


def _choose(user: User, marker: str, option: str) -> None:
    user.find(marker=marker).click()
    user.find(option).click()


async def test_the_sheets_defaults_come_in_on_the_first_visit(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/benchmarki")
        await user.should_see(marker="benchmark-row")

        rows = _rows(user)
        assert [row[0] for row in rows] == [
            "Portfel",
            "CPI",
            "LON:ACWI*",
            "LON:CSPX*",
            "AMS:V80A*",
            "WSE:ETFBW20TR*",
            "WSE:ETFBS80TR*",
        ]
        assert rows[0][1] == f"4{NBSP}000,00{NBSP}zł"
        # Without a price the money waits as cash: the Portfolio equals them
        assert rows[2][1:3] == [f"4{NBSP}000,00{NBSP}zł", f"+0,00{NBSP}zł"]
        with user.scope(marker="benchmarks-table"):
            await user.should_see("Benchmark nie ma notowań z całego okresu")
        await user.should_see(marker="chart-benchmarks-history")
        await user.should_see(marker="chart-benchmarks-values")


async def test_cpi_inflates_the_deposits_and_the_portfolio_falls_behind_it(engine: Engine) -> None:
    save_setting(engine, BENCHMARKS_SEEDED, "1")
    add_benchmark(engine, Benchmark(BenchmarkKind.CPI))
    async with user_simulation(_shell(engine)) as user:
        await user.open("/benchmarki")
        await user.should_see(marker="benchmark-row")

        _, cpi = _rows(user)
        # 4000 PLN from the end of 3.08: 28/31 of August's 1 % and all of September's, then October unpublished
        value = Decimal(4000) * Decimal("1.01") ** (Decimal(28) / 31) * Decimal("1.01")
        assert cpi[1] == f"{value:,.2f}".replace(",", NBSP).replace(".", ",") + f"{NBSP}zł"
        assert cpi[2].startswith("-")


async def test_adding_cpi_plus_points_and_another_account(engine: Engine) -> None:
    save_setting(engine, BENCHMARKS_SEEDED, "1")
    async with user_simulation(_shell(engine)) as user:
        await user.open("/benchmarki")
        await user.should_see(marker="benchmark-add")

        _choose(user, "benchmark-kind", "CPI (inflacja)")
        user.find(marker="benchmark-offset").type("3")
        user.find(marker="benchmark-add-button").click()
        await user.should_see(f"CPI + 3{NBSP}pp/rok")

        _choose(user, "benchmark-kind", "Konto")
        _choose(user, "benchmark-account", "XTB")
        user.find(marker="benchmark-add-button").click()
        await user.should_see("Konto XTB")

        # The same again is refused
        user.find(marker="benchmark-add-button").click()
        await user.should_see("Taki benchmark już jest na liście.")

    assert [b.kind for b in list_benchmarks(engine)] == [BenchmarkKind.CPI, BenchmarkKind.ACCOUNT]


async def test_a_benchmark_can_be_hidden_from_the_chart_and_removed(engine: Engine) -> None:
    save_setting(engine, BENCHMARKS_SEEDED, "1")
    cpi = add_benchmark(engine, Benchmark(BenchmarkKind.CPI))
    async with user_simulation(_shell(engine)) as user:
        await user.open("/benchmarki")
        await user.should_see(marker=f"benchmark-shown-{cpi.id}")

        user.find(marker=f"benchmark-shown-{cpi.id}").click()
        assert not list_benchmarks(engine)[0].shown

        user.find(marker=f"benchmark-delete-{cpi.id}").click()
        await user.should_not_see(marker=f"benchmark-shown-{cpi.id}")

    assert list_benchmarks(engine) == []


async def test_an_account_scope_compares_that_accounts_money(engine: Engine) -> None:
    save_setting(engine, BENCHMARKS_SEEDED, "1")
    add_benchmark(engine, Benchmark(BenchmarkKind.ACCOUNT, account_id=1))
    add_benchmark(engine, Benchmark(BenchmarkKind.ACCOUNT, account_id=2))
    async with user_simulation(_shell(engine)) as user:
        await user.open("/benchmarki")
        await user.should_see(marker="benchmark-row")
        user.find(marker="view-scope").click()
        await user.should_see(marker="scope-menu")
        user.find(marker="scope-1").click()

        # IKE is no benchmark of itself
        await user.should_not_see("Konto IKE")
        await user.should_see(f"1{NBSP}000,00{NBSP}zł")
        assert [row[0] for row in _rows(user)] == ["Portfel", "Konto XTB"]
