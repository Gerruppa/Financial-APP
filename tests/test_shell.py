"""Smoke tests of the app shell (variant B from the UI prototype), run without a browser."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation

from financial_app.persistence.db import init_db
from financial_app.ui.shell import build_shell

TABS = [
    "Dashboard",
    "Wyniki",
    "Portfolio",
    "Transakcje",
    "Strategie inwestycyjne",
    "Obligacje",
    "Benchmarki",
    "Ustawienia",
]


@pytest.fixture
async def user(tmp_path: Path) -> AsyncIterator[User]:
    engine = init_db(tmp_path / "app.sqlite3")
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


async def test_header_offers_total_view_scope(user: User) -> None:
    with user.scope(marker="header"):
        await user.should_see("Total")


async def test_plus_button_opens_transaction_dialog(user: User) -> None:
    await user.should_not_see("Nowa transakcja")

    user.find(marker="add-transaction").click()

    await user.should_see("Nowa transakcja")
