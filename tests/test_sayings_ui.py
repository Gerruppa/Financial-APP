"""The saying of the day in the window (issue #178): a line at the menu's foot, hidden by a switch in Wygląd i
widoczność."""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from nicegui.testing import user_simulation
from sqlalchemy import Engine

from financial_app.domain.sayings import SAYINGS, saying_of_the_day
from financial_app.persistence.db import init_db
from financial_app.ui.shell import build_shell

TODAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 9, 0)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _shell(engine: Engine) -> Callable[[], None]:
    return lambda: build_shell(engine, now=lambda: NOW)


async def test_the_saying_of_the_day_is_in_the_menu_alone(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")

        with user.scope(marker="menu-saying"):
            await user.should_see(saying_of_the_day(TODAY).text)
        await user.should_see(marker="investment-goal")
        await user.should_not_see(marker="dashboard-saying")


def _day_of(work: str) -> datetime:
    """A moment whose saying comes from ``work``."""
    day = next(day for n in range(len(SAYINGS)) if saying_of_the_day(day := TODAY + timedelta(days=n)).work == work)
    return datetime.combine(day, NOW.time())


async def test_a_walaszek_saying_is_signed_with_its_work_and_author(engine: Engine) -> None:
    moment = _day_of("Kapitan Bomba")
    async with user_simulation(lambda: build_shell(engine, now=lambda: moment)) as user:
        await user.open("/")

        with user.scope(marker="menu-saying"):
            await user.should_see("— Kapitan Bomba, Bartosz Walaszek")


async def test_a_chlopaki_z_barakow_saying_is_signed_with_its_work_alone(engine: Engine) -> None:
    moment = _day_of("Chłopaki z baraków")
    async with user_simulation(lambda: build_shell(engine, now=lambda: moment)) as user:
        await user.open("/")

        with user.scope(marker="menu-saying"):
            await user.should_see("— Chłopaki z baraków")
            await user.should_not_see("Walaszek")


async def test_a_switch_hides_the_saying(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="ui-visibility-sayings").click()

        await user.should_not_see(marker="menu-saying")
