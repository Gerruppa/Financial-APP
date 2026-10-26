"""Ustawienia is split into sections behind buttons: only the chosen section is on screen, run without a browser."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.persistence.db import init_db
from financial_app.ui.shell import build_shell


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
async def user(engine: Engine) -> AsyncIterator[User]:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        yield user


async def test_section_buttons_are_listed(user: User) -> None:
    for marker in ("settings-section-accounts", "settings-section-asset-classes", "settings-section-instruments"):
        await user.should_see(marker=marker)


async def test_a_section_button_shows_that_section(user: User) -> None:
    user.find(marker="settings-section-asset-classes").click()
    await user.should_see(marker="asset-classes")
    user.find(marker="settings-section-accounts").click()
    await user.should_see(marker="accounts")
