"""The Wyniki tab (issue #74, spec section 5): the View Scope's results over the period and the fixed periods per Total
and Account, with History computed in the test from the cache alone."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.bonds import CpiReading
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell, dividend
from financial_app.persistence.accounts import add_account
from financial_app.persistence.bond_data import save_cpi
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import add_transactions
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates
from financial_app.sources.portfolio_history import PortfolioHistory
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
TODAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 9, 0)

type Compute = Callable[..., Awaitable[list[DayValue]]]


def _percent(text: str) -> str:
    return f"{text}{NBSP}%"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """IKE: 1000 PLN in on 3.08, 10 PZU bought at 50 with a 5 PLN commission (History has no PZU price, so it values
    PZU at cost), a 20 PLN Dividend on 1.10; XTB: 3000 PLN in on 3.08."""
    engine = init_db(tmp_path / "app.sqlite3")
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    xtb = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id
    shares = next(c for c in list_asset_classes(engine) if c.name == "Akcje polskie")
    pzu = add_instrument(engine, InstrumentDraft("PZU", shares.id, "PLN")).id
    add_transactions(
        engine,
        [
            TransactionDraft(ike, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(1000)),
            TransactionDraft(xtb, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(3000)),
            buy_or_sell(ike, date(2026, 8, 4), TransactionType.BUY, pzu, Decimal(10), Decimal(50), Decimal(5)),
            dividend(ike, date(2026, 10, 1), Decimal(20), instrument_id=pzu),
        ],
    )
    return engine


async def _inline(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
    return function(*args)


def _shell(engine: Engine, compute: Compute = _inline) -> Callable[[], None]:
    quotes = QuoteHistory(engine, lambda url: "Brak danych", lambda: TODAY, lambda: NOW, lambda url: None)
    history = PortfolioHistory(engine, quotes, NbpRates(engine), lambda: TODAY, compute)
    return lambda: build_shell(engine, now=lambda: NOW, history=history)


def _rows(user: User) -> list[list[str]]:
    rows = sorted(user.find(marker="results-row").elements, key=lambda element: element.id)
    return [[d.text for d in row.descendants() if isinstance(d, ui.label)] for row in rows]


async def test_the_results_of_the_period_follow_history(engine: Engine) -> None:
    # Since inception: 4000 PLN in grows to 4020 PLN with the Dividend; the TWR never fell
    async with user_simulation(_shell(engine)) as user:
        await user.open("/wyniki")

        await user.should_see(marker="results-twr", content=_percent("0,50"))
        await user.should_see(marker="results-max-drawdown", content=_percent("0,00"))
        await user.should_see(marker="results-recovery", content="—")
        await user.should_see(marker="results-real", content="—")
        await user.should_see("brak CPI GUS za ten okres")
        await user.should_see(marker="chart-results-drawdown")


async def test_the_real_return_is_the_twr_after_the_gus_cpi_published_so_far(engine: Engine) -> None:
    # Prices flat in August and September, October not published yet: the real return is the TWR
    save_cpi(engine, [CpiReading(2026, 8, None, Decimal(100)), CpiReading(2026, 9, None, Decimal(100))])
    async with user_simulation(_shell(engine)) as user:
        await user.open("/wyniki")

        await user.should_see(marker="results-real", content=_percent("0,50"))
        await user.should_see(f"inflacja (CPI) {_percent('0,00')} · CPI do 09.2026")


async def test_the_table_lists_the_total_then_each_account_over_the_fixed_periods(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/wyniki")
        await user.should_see(marker="results-row")

        # YTD, 1R, 3L and Od początku all start at the first Transaction, each as XIRR and TWR
        total, xtb, ike = _rows(user)
        assert total[0] == "Total" and xtb[0] == "XTB" and ike[0] == "IKE"
        assert ike[2::2] == [_percent("2,00")] * 4
        assert xtb[1:] == [_percent("0,00")] * 8


async def test_an_account_scope_shows_only_that_accounts_results(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/wyniki")
        await user.should_see(marker="results-row")
        user.find(marker="view-scope").click()
        await user.should_see(marker="scope-menu")
        user.find(marker="scope-1").click()

        await user.should_see(marker="results-twr", content=_percent("2,00"))
        assert [row[0] for row in _rows(user)] == ["IKE"]


async def test_choosing_a_period_recomputes_the_results(engine: Engine) -> None:
    # Since 3.08 (70 days) and over 1M from 12.09 (30 days), 4000 PLN grows to 4020 PLN: 2,63 % and 6,26 % a year
    async with user_simulation(_shell(engine)) as user:
        await user.open("/wyniki")
        await user.should_see(marker="results-xirr", content=_percent("2,63"))

        with user.scope(marker="period-selector"):
            user.find("1M").click()

        await user.should_see(marker="results-xirr", content=_percent("6,26"))
        await user.should_see(marker="results-twr", content=_percent("0,50"))


async def test_the_results_wait_for_history(engine: Engine) -> None:
    computed = asyncio.Event()

    async def slow(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
        await computed.wait()
        return function(*args)

    async with user_simulation(_shell(engine, slow)) as user:
        await user.open("/wyniki")

        await user.should_see(marker="results-pending")
        computed.set()
        await user.should_see(marker="results-twr", content=_percent("0,50"))


async def test_without_transactions_there_are_no_results(tmp_path: Path) -> None:
    async with user_simulation(_shell(init_db(tmp_path / "empty.sqlite3"))) as user:
        await user.open("/wyniki")

        await user.should_see(marker="results-empty")
        await user.should_not_see(marker="results-twr")


async def test_the_xirr_and_twr_tiles_explain_themselves_behind_an_info_icon(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/wyniki")
        await user.should_see(marker="results-xirr")

        for name, words in (("xirr", "terminów i kwot wpłat"), ("twr", "żadnych wpłat")):
            [icon] = user.find(marker=f"info-results-{name}").elements
            [tooltip] = [element for element in icon.descendants() if isinstance(element, ui.tooltip)]
            assert words in tooltip.text
