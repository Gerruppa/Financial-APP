"""The Stooq Source Symbol in the Instrument dialog and the Stooq API key in Ustawienia (issue #33), without a
browser."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.prices import STOOQ
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_instruments
from financial_app.persistence.settings import STOOQ_API_KEY, load_setting, save_setting
from financial_app.ui.shell import build_shell


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
async def user(engine: Engine) -> AsyncIterator[User]:
    async with user_simulation(lambda: build_shell(engine, sources={})) as user:
        await user.open("/ustawienia")
        yield user


async def test_an_index_gets_its_stooq_symbol_in_the_instrument_dialog(user: User, engine: Engine) -> None:
    add_instrument(engine, InstrumentDraft("WIG", 12, "PLN", "GPW"))
    await user.open("/ustawienia")

    user.find(marker="edit-instrument").click()
    user.find(marker="instrument-symbol-stooq").clear().type("wig")
    user.find("Zapisz").click()
    await user.should_not_see(marker="instrument-dialog")

    assert list_instruments(engine)[0].source_symbols == {STOOQ: "wig"}
    await user.should_see("Stooq wig")


async def test_the_stooq_api_key_is_saved_in_the_settings(user: User, engine: Engine) -> None:
    user.find(marker="stooq-api-key").clear().type(" abc123 ")
    user.find(marker="save-stooq-api-key").click()

    await user.should_see("Zapisano klucz API Stooq.")
    assert load_setting(engine, STOOQ_API_KEY) == "abc123"


async def test_a_saved_stooq_api_key_is_filled_in(engine: Engine) -> None:
    save_setting(engine, STOOQ_API_KEY, "abc123")

    async with user_simulation(lambda: build_shell(engine, sources={})) as user:
        await user.open("/ustawienia")

        key = user.find(marker="stooq-api-key", kind=ui.input).elements.pop()
        assert key.value == "abc123"
