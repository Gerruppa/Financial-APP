"""Tests of the discreet mode: the header's eye button blurs the amounts and the choice is remembered."""

import re
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.formatting import format_amount, format_pln, format_rate
from financial_app.persistence.db import init_db
from financial_app.persistence.settings import UI_DISCREET, load_setting, save_setting
from financial_app.ui.discreet import MONEY_PATTERN, DiscreetChoice
from financial_app.ui.shell import build_shell


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
async def user(engine: Engine) -> AsyncIterator[User]:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")
        yield user


def test_the_pattern_finds_the_amounts_the_app_formats() -> None:
    pattern = re.compile(MONEY_PATTERN)
    for text in (
        format_pln(Decimal("15912.3")),
        format_pln(Decimal("-1234567.5"), signed=True),
        format_amount(Decimal("1505"), "USD"),
        format_rate(Decimal("3.6045")),
    ):
        # The sign stays readable; it is the digits and the unit that blur
        found = pattern.search(text)
        assert found and found.group() == text.lstrip("+-"), text


def test_the_pattern_leaves_dates_and_percents_alone() -> None:
    pattern = re.compile(MONEY_PATTERN)
    assert not pattern.search("07.03.2026")
    assert not pattern.search("6,40 %")


def test_the_choice_starts_off_and_remembers_being_switched(engine: Engine) -> None:
    choice = DiscreetChoice(engine)
    assert choice.on is False

    choice.toggle()

    assert choice.on is True
    assert load_setting(engine, UI_DISCREET) == "1"
    assert DiscreetChoice(engine).on is True


async def test_the_eye_button_in_the_header_switches_the_mode(user: User, engine: Engine) -> None:
    await user.should_see(marker="discreet-toggle")

    user.find(marker="discreet-toggle").click()
    assert load_setting(engine, UI_DISCREET) == "1"

    user.find(marker="discreet-toggle").click()
    assert load_setting(engine, UI_DISCREET) == "0"


async def test_the_mode_is_on_from_the_start_when_remembered(engine: Engine) -> None:
    save_setting(engine, UI_DISCREET, "1")
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")
        button = user.find(marker="discreet-toggle").elements.pop()
        assert button.props["icon"] == "visibility_off"
