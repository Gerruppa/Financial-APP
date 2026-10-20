"""The changelog (issue #200): the shipped file, the version under the logo opening it, "Co nowego" once a version."""

from pathlib import Path

import pytest
from nicegui.testing import user_simulation
from sqlalchemy import Engine

from financial_app import __version__
from financial_app.persistence.db import init_db
from financial_app.persistence.settings import LAST_SEEN_VERSION, load_setting, save_setting
from financial_app.ui.changelog import load_changelog
from financial_app.ui.shell import build_shell


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def test_the_shipped_changelog_has_the_current_version() -> None:
    changelog = load_changelog()

    assert changelog.release(__version__) is not None, f"changelog.md nie ma sekcji wersji {__version__}"
    assert changelog.releases[0].version == __version__
    assert changelog.release("1.0.0") is not None


async def test_clicking_the_version_opens_every_released_version(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")
        await user.should_not_see(marker="changelog")

        user.find(marker="app-version").click()

        await user.should_see(marker="changelog")
        with user.scope(marker="changelog"):
            await user.should_see("Historia zmian")
            await user.should_see("Pierwsze wydanie.")
            await user.should_see("Nowe funkcje")
            await user.should_not_see("Nieopublikowane")


async def test_a_first_start_only_records_the_version(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")
        await user.should_see(marker="app-version")

        await user.should_not_see(marker="changelog")
    assert load_setting(engine, LAST_SEEN_VERSION) == __version__


async def test_the_first_start_of_a_new_version_shows_it_once(engine: Engine) -> None:
    save_setting(engine, LAST_SEEN_VERSION, "0.9.0")
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")

        await user.should_see(marker="changelog")
        with user.scope(marker="changelog"):
            await user.should_see("Co nowego")
            await user.should_see(__version__)
    assert load_setting(engine, LAST_SEEN_VERSION) == __version__

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")
        await user.should_see(marker="app-version")
        await user.should_not_see(marker="changelog")


async def test_going_back_to_an_older_version_keeps_the_newer_one_seen(engine: Engine) -> None:
    save_setting(engine, LAST_SEEN_VERSION, "99.0.0")
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")
        await user.should_see(marker="app-version")

        await user.should_not_see(marker="changelog")
    assert load_setting(engine, LAST_SEEN_VERSION) == "99.0.0"
