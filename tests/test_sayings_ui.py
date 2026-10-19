"""The saying of the day in the window (issue #178): a card beside the Investment Goal and a line at the menu's foot,
both hidden by one switch in Wygląd i widoczność."""

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import pytest
from nicegui.testing import user_simulation
from sqlalchemy import Engine

from financial_app.domain.sayings import saying_of_the_day
from financial_app.persistence.db import init_db
from financial_app.ui.shell import build_shell

TODAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 9, 0)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _shell(engine: Engine) -> Callable[[], None]:
    return lambda: build_shell(engine, now=lambda: NOW)


async def test_the_dashboard_and_the_menu_show_the_sayings_of_the_day(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")

        with user.scope(marker="dashboard-saying"):
            await user.should_see(saying_of_the_day(TODAY).text)
            await user.should_see("Kapitan Bomba, Bartosz Walaszek")
        with user.scope(marker="menu-saying"):
            await user.should_see(saying_of_the_day(TODAY, menu=True).text)


async def test_one_switch_hides_both_sayings(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="ui-visibility-sayings").click()

        await user.should_not_see(marker="menu-saying")
        await user.open("/")
        await user.should_not_see(marker="dashboard-saying")
        await user.should_see(marker="investment-goal")
