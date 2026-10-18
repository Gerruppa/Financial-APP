"""Wygląd i widoczność in Ustawienia (issue #155): switches hide Dashboard tiles, sections, charts and tabs at once and
for good, and the Podstawowy and Pełny View Profiles set them in one click."""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import add_transactions
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates
from financial_app.sources.portfolio_history import PortfolioHistory
from financial_app.ui.shell import build_shell

TODAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 9, 0)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """IKE: 1000 PLN in and 10 PZU bought at 50, PZU now 60 (Manual Price)."""
    engine = init_db(tmp_path / "app.sqlite3")
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    shares = next(c for c in list_asset_classes(engine) if c.name == "Akcje polskie")
    pzu = add_instrument(engine, InstrumentDraft("PZU", shares.id, "PLN", manual_price=Decimal(60))).id
    add_transactions(
        engine,
        [
            TransactionDraft(ike, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(1000)),
            buy_or_sell(ike, date(2026, 8, 4), TransactionType.BUY, pzu, Decimal(10), Decimal(50), Decimal(5)),
        ],
    )
    return engine


async def _inline(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
    return function(*args)


def _shell(engine: Engine) -> Callable[[], None]:
    quotes = QuoteHistory(engine, lambda url: "Brak danych", lambda: TODAY, lambda: NOW, lambda url: None)
    history = PortfolioHistory(engine, quotes, NbpRates(engine), lambda: TODAY, _inline)
    return lambda: build_shell(engine, now=lambda: NOW, history=history)


async def _switch(user: User, key: str) -> None:
    await user.open("/ustawienia")
    user.find(marker=f"ui-visibility-{key}").click()


async def test_a_hidden_tile_leaves_the_dashboard_and_stays_hidden_in_a_new_window(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await user.should_see(marker="total-cash")

        await _switch(user, "tile-cash")
        await user.open("/")

        await user.should_not_see(marker="total-cash")
        await user.should_see(marker="total-value")

    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await user.should_not_see(marker="total-cash")


async def test_a_hidden_chart_leaves_the_dashboard(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await _switch(user, "chart-allocation")
        await user.open("/")

        await user.should_not_see(marker="chart-allocation")
        await user.should_see(marker="chart-accounts")


async def test_a_hidden_tab_leaves_the_menu_at_once_yet_its_address_still_opens_it(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await _switch(user, "tab-benchmarki")

        with user.scope(marker="nav-menu"):
            await user.should_not_see("Benchmarki")
            await user.should_see("Ustawienia")
        await user.open("/benchmarki")
        with user.scope(marker="page-content"):
            await user.should_see("Benchmarki")


async def test_ustawienia_and_the_main_tabs_have_no_switch(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/ustawienia")

        for key in ("tab-ustawienia", "tab-", "tab-portfolio", "tab-transakcje"):
            await user.should_not_see(marker=f"ui-visibility-{key}")


async def test_podstawowy_keeps_the_basics_and_przywroc_domyslne_shows_everything_again(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/ustawienia")
        await user.should_see(marker="ui-profile", content="Pełny")

        user.find(marker="ui-profile-basic").click()

        await user.should_see(marker="ui-profile", content="Podstawowy")
        with user.scope(marker="nav-menu"):
            await user.should_not_see("Wyniki")
            await user.should_not_see("Obligacje")
        await user.open("/")
        await user.should_see(marker="total-value")
        await user.should_see(marker="account-table")
        await user.should_not_see(marker="total-cash")
        await user.should_not_see(marker="chart-waterfall")
        await user.should_not_see(marker="dashboard-strategy")

        await user.open("/ustawienia")
        user.find(marker="ui-visibility-restore").click()

        await user.should_see(marker="ui-profile", content="Pełny")
        with user.scope(marker="nav-menu"):
            await user.should_see("Obligacje")
        await user.open("/")
        await user.should_see(marker="total-cash")
        await user.should_see(marker="chart-waterfall")


async def test_changing_a_switch_by_hand_makes_the_profile_custom(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await _switch(user, "tile-xirr")

        await user.should_see(marker="ui-profile", content="Własny")
