"""Smoke tests of the app shell (variant B from the UI prototype), run without a browser."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.persistence.db import init_db
from financial_app.persistence.settings import UI_THEME, load_setting
from financial_app.ui.shell import build_shell

TABS = [
    "Dashboard",
    "Wyniki",
    "Portfolio",
    "Transakcje",
    "Strategie inwestycyjne",
    "Dochód stały",
    "Benchmarki",
    "Podsumowanie sprzedaży",
    "Dochód pasywny",
    "Ustawienia",
    "Pomoc",
]


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
async def user(engine: Engine) -> AsyncIterator[User]:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")
        yield user


async def test_menu_shows_every_tab_and_starts_on_dashboard(user: User) -> None:
    with user.scope(marker="nav-menu"):
        for tab in TABS:
            await user.should_see(tab)
    with user.scope(marker="page-content"):
        await user.should_see("Dashboard")


@pytest.mark.parametrize("tab", TABS[1:])
async def test_clicking_a_menu_entry_opens_its_tab(user: User, tab: str) -> None:
    with user.scope(marker="nav-menu"):
        user.find(tab).click()

    with user.scope(marker="page-content"):
        await user.should_see(tab)


async def test_the_menu_names_the_app_and_its_version(user: User) -> None:
    with user.scope(marker="nav-menu"):
        await user.should_see("KAPITA")
        await user.should_see("1.0.0")
        user.find(marker="app-logo")


async def test_the_menu_lights_the_tab_on_screen(user: User) -> None:
    with user.scope(marker="nav-menu"):
        user.find("Wyniki").click()
    with user.scope(marker="page-content"):
        await user.should_see("Wyniki")

    with user.scope(marker="nav-menu"):
        lit_tabs = [button.text for button in user.find(ui.button).elements if "k-active" in button.classes]
    assert lit_tabs == ["Wyniki"]


async def test_the_theme_button_switches_to_golden_and_remembers_it(user: User, engine: Engine) -> None:
    await user.should_see(marker="theme-toggle")

    user.find(marker="theme-toggle").click()

    assert load_setting(engine, UI_THEME) == "golden"


async def test_header_offers_total_view_scope(user: User) -> None:
    with user.scope(marker="header"):
        await user.should_see("Total")


async def test_the_dashboard_has_no_plus_button(user: User) -> None:
    await user.should_see(marker="dashboard")

    await user.should_not_see(marker="add-transaction")


async def test_plus_button_opens_transaction_dialog(user: User) -> None:
    await user.open("/transakcje")
    await user.should_not_see("Nowa transakcja")

    user.find(marker="add-transaction").click()

    await user.should_see("Nowa transakcja")
