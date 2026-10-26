"""The command palette in the header search: commands listed while typing, ">" for all of them, Enter or a click runs
one (go to a tab, add a Transaction, switch the Theme, the discreet mode)."""

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.instrument_search import FoundListings
from financial_app.persistence.db import init_db
from financial_app.persistence.settings import UI_DISCREET, UI_THEME, load_setting
from financial_app.ui.shell import TABS, build_shell


class RecordingSearch:
    """A search service that finds nothing and notes the queries it was asked."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def search(self, query: str) -> FoundListings:
        self.asked.append(query)
        return FoundListings([], ())


async def _until(condition: Callable[[], bool]) -> None:
    """Wait (at most 2 s) for ``condition``: the Enter key's handler runs on the event loop after the test's trigger."""
    for _ in range(40):
        if condition():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the command did not run")


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def search() -> RecordingSearch:
    return RecordingSearch()


@pytest.fixture
async def user(engine: Engine, search: RecordingSearch) -> AsyncIterator[User]:
    async with user_simulation(lambda: build_shell(engine, search=search)) as user:
        await user.open("/")
        yield user


async def test_a_typed_word_lists_the_commands_that_start_with_it(user: User) -> None:
    user.find(marker="header-search").type("portf")

    await user.should_see("Polecenia")
    await user.should_see("Przejdź do: Portfolio")


async def test_clicking_a_navigation_command_opens_the_tab(user: User) -> None:
    user.find(marker="header-search").type("portf")
    await user.should_see(marker="command-result")

    user.find(marker="command-result").click()

    await user.should_see(marker="portfolio")


async def test_the_prefix_lists_every_command_and_no_search_results(user: User, search: RecordingSearch) -> None:
    user.find(marker="header-search").type(">")

    await user.should_see(marker="command-result")
    assert len(user.find(marker="command-result").elements) >= len(TABS)
    await user.should_not_see("Znalezione")
    assert search.asked == []


async def test_enter_runs_the_highlighted_command_to_switch_the_theme(user: User, engine: Engine) -> None:
    user.find(marker="header-search").type("> motyw").trigger("keydown.enter")

    await _until(lambda: load_setting(engine, UI_THEME) == "golden")


async def test_the_discreet_mode_is_a_command(user: User, engine: Engine) -> None:
    user.find(marker="header-search").type(">dyskr").trigger("keydown.enter")

    await _until(lambda: load_setting(engine, UI_DISCREET) == "1")


async def test_add_transaction_opens_its_dialog(user: User) -> None:
    user.find(marker="header-search").type("> dodaj").trigger("keydown.enter")

    await user.should_see("Nowa transakcja")


async def test_a_query_no_command_matches_says_so_in_command_mode(user: User) -> None:
    user.find(marker="header-search").type(">xyzxyz")

    await user.should_see("Brak pasujących poleceń")
