"""The View Scope switcher, the breadcrumbs, the tabs following the scope and the period selector (issue #71, spec
section 5 and 6.1), with History computed in the test from the cache alone."""

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
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.transactions import TransactionDraft, TransactionType, cash_transfer
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.settings import PERIOD, VIEW_SCOPE, load_setting, save_setting
from financial_app.persistence.transactions import add_transactions
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates
from financial_app.sources.portfolio_history import PortfolioHistory
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
TODAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 9, 0)

type Compute = Callable[..., Awaitable[list[DayValue]]]


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = init_db(tmp_path / "app.sqlite3")
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    xtb = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id
    add_account(engine, AccountDraft("Stare", "Bank", AccountType.REGULAR, ("PLN",), active=False))
    add_transactions(
        engine,
        [
            TransactionDraft(ike, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(1000), comment="wpłata IKE"),
            TransactionDraft(xtb, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(3000), comment="wpłata XTB"),
            cash_transfer(xtb, date(2026, 10, 5), ike, Decimal(500), comment="przelew"),
        ],
    )
    return engine


async def _inline(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
    return function(*args)


def _shell(engine: Engine, compute: Compute = _inline) -> Callable[[], None]:
    quotes = QuoteHistory(engine, lambda url: "Brak danych", lambda: TODAY, lambda: NOW, lambda url: None)
    history = PortfolioHistory(engine, quotes, NbpRates(engine), lambda: TODAY, compute)
    return lambda: build_shell(engine, now=lambda: NOW, history=history)


def _entries(user: User) -> list[list[str]]:
    """The switcher's rows top to bottom, each as its texts."""
    rows = sorted(user.find(marker="scope-entry").elements, key=lambda element: element.id)
    return [[d.text for d in row.descendants() if isinstance(d, ui.label)] for row in rows]


async def test_the_switcher_offers_total_then_accounts_by_value_with_their_daily_change(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        with user.scope(marker="header"):
            await user.should_see("Total")
        # The menu shows "—" until History is computed
        await user.should_see(marker="total-net-deposits", content=f"4{NBSP}000,00{NBSP}zł")

        user.find(marker="view-scope").click()

        await user.should_see(marker="scope-menu")
        assert _entries(user) == [
            ["Total", f"4{NBSP}000,00{NBSP}zł", f"0,00{NBSP}zł"],
            ["XTB", f"2{NBSP}500,00{NBSP}zł", f"0,00{NBSP}zł"],
            ["IKE", f"1{NBSP}500,00{NBSP}zł", f"0,00{NBSP}zł"],
        ]
        await user.should_not_see("Stare")
        user.find(marker="toggle-inactive").click()
        await user.should_see("Stare (nieaktywne)")
        assert _entries(user)[-1][0] == "Stare (nieaktywne)"


async def test_choosing_an_account_filters_the_tabs_and_the_breadcrumbs_return_to_total(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/portfolio")
        user.find(marker="view-scope").click()
        await user.should_see(marker="scope-menu")
        user.find(marker="scope-2").click()

        await user.should_see(marker="breadcrumbs")
        await user.should_not_see(marker="scope-menu")
        with user.scope(marker="header"):
            await user.should_see("XTB")
        with user.scope(marker="breadcrumbs"):
            await user.should_see("Total")
        with user.scope(marker="portfolio"):
            await user.should_see("XTB")
            await user.should_not_see("IKE")
        assert load_setting(engine, VIEW_SCOPE) == "2"

        await user.open("/transakcje")
        with user.scope(marker="transactions"):
            await user.should_see("wpłata XTB")
            await user.should_see("przelew")
            await user.should_not_see("wpłata IKE")

        with user.scope(marker="breadcrumbs"):
            user.find("Total").click()
        with user.scope(marker="transactions"):
            await user.should_see("wpłata IKE")
        await user.should_not_see(marker="breadcrumbs")
        assert load_setting(engine, VIEW_SCOPE) == "total"


async def test_the_last_scope_is_remembered_and_a_gone_account_falls_back_to_total(engine: Engine) -> None:
    save_setting(engine, VIEW_SCOPE, "1")
    async with user_simulation(_shell(engine)) as user:
        await user.open("/transakcje")
        with user.scope(marker="header"):
            await user.should_see("IKE")
        with user.scope(marker="transactions"):
            await user.should_not_see("wpłata XTB")

    save_setting(engine, VIEW_SCOPE, "99")
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        with user.scope(marker="header"):
            await user.should_see("Total")


async def test_values_show_a_dash_while_history_loads(engine: Engine) -> None:
    computed = asyncio.Event()

    async def slow(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
        await computed.wait()
        return function(*args)

    async with user_simulation(_shell(engine, slow)) as user:
        await user.open("/")
        user.find(marker="view-scope").click()

        await user.should_see(marker="scope-menu")
        assert _entries(user)[0] == ["Total", "—", "—"]
        computed.set()


async def test_the_period_selector_shows_its_range_and_is_remembered(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        with user.scope(marker="period-selector"):
            await user.should_see("03.08.2026 – 12.10.2026")
            user.find("1M").click()
        # On the Dashboard the selector sits in the main card, drawn again for the new period
        await user.should_see(marker="period-range", content="12.09.2026 – 12.10.2026")
        assert load_setting(engine, PERIOD) == "1m"

        with user.scope(marker="period-selector"):
            user.find("Własny").click()
        await user.should_see(marker="period-from")
        user.find(marker="period-from").type("03.10.2026")
        user.find(marker="period-to").type("10.10.2026")
        user.find("Zastosuj").click()

        await user.should_see(marker="period-range", content="03.10.2026 – 10.10.2026")
        assert load_setting(engine, PERIOD) == "custom:2026-10-03:2026-10-10"

        await user.open("/wyniki")
        with user.scope(marker="period-selector"):
            await user.should_see("03.10.2026 – 10.10.2026")


async def test_a_custom_period_ending_before_it_starts_is_refused(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        with user.scope(marker="period-selector"):
            user.find("Własny").click()
        await user.should_see(marker="period-from")
        user.find(marker="period-from").type("10.10.2026")
        user.find(marker="period-to").type("03.10.2026")
        user.find("Zastosuj").click()

        await user.should_see("Data początkowa okresu musi poprzedzać końcową.")
        assert load_setting(engine, PERIOD) is None


async def test_an_account_scope_is_outlined_in_the_header_breadcrumbs_and_menu(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        [switcher] = user.find(marker="view-scope").elements
        assert "k-scope-chosen" not in switcher.classes

        user.find(marker="view-scope").click()
        await user.should_see(marker="scope-menu")
        user.find(marker="scope-2").click()

        await user.should_see(marker="breadcrumb-scope", content="XTB")
        [crumb] = user.find(marker="breadcrumb-scope").elements
        assert "k-scope-chosen" in crumb.classes
        assert "k-scope-chosen" in switcher.classes
        user.find(marker="view-scope").click()
        await user.should_see(marker="scope-2")
        [chosen] = user.find(marker="scope-2").elements
        assert {"k-highlight", "k-scope-row"} <= set(chosen.classes)

        with user.scope(marker="breadcrumbs"):
            user.find("Total").click()
        await user.should_not_see(marker="breadcrumbs")
        assert "k-scope-chosen" not in switcher.classes
