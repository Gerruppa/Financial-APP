"""Ustawienia > Wyczyść dane: two confirmations, a warning and then the typed phrase, run without a browser."""

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.transactions import TransactionDraft, TransactionType
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.reset import PortfolioCounts, portfolio_counts
from financial_app.persistence.transactions import add_transaction
from financial_app.ui.reset import CONFIRMATION_PHRASE
from financial_app.ui.shell import build_shell

FULL = PortfolioCounts(accounts=1, instruments=1, transactions=1)
EMPTY = PortfolioCounts(accounts=0, instruments=0, transactions=0)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = init_db(tmp_path / "app.sqlite3")
    account = add_account(engine, AccountDraft("Moje XTB", "XTB", AccountType.REGULAR, ("PLN",)))
    add_instrument(engine, InstrumentDraft("GPW:PKN", list_asset_classes(engine)[1].id, "PLN"))
    add_transaction(engine, TransactionDraft(account.id, date(2024, 1, 2), TransactionType.DEPOSIT, Decimal(1000)))
    return engine


@pytest.fixture
async def user(engine: Engine) -> AsyncIterator[User]:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        yield user


def _confirm_button(user: User) -> ui.button:
    [button] = user.find(marker="clear-data-confirm").elements
    assert isinstance(button, ui.button)
    return button


async def test_the_warning_lists_what_will_be_removed(user: User, engine: Engine) -> None:
    user.find(marker="clear-data").click()

    await user.should_see("Wyczyścić wszystkie dane?")
    await user.should_see("Konta: 1")
    await user.should_see("Instrumenty: 1")
    await user.should_see("Transakcje: 1")
    assert portfolio_counts(engine) == FULL


async def test_cancelling_the_warning_keeps_the_data(user: User, engine: Engine) -> None:
    user.find(marker="clear-data").click()
    user.find(marker="clear-data-cancel").click()

    assert not any(dialog.value for dialog in user.find(ui.dialog).elements)
    assert portfolio_counts(engine) == FULL


async def test_the_final_button_stays_disabled_until_the_phrase_is_typed_exactly(user: User, engine: Engine) -> None:
    user.find(marker="clear-data").click()
    user.find(marker="clear-data-next").click()

    await user.should_see(CONFIRMATION_PHRASE)
    assert not _confirm_button(user).enabled
    user.find(marker="clear-data-phrase").type(CONFIRMATION_PHRASE.lower())
    assert not _confirm_button(user).enabled
    user.find(marker="clear-data-phrase").clear().type(f"  {CONFIRMATION_PHRASE} ")
    assert _confirm_button(user).enabled
    assert portfolio_counts(engine) == FULL


async def test_cancelling_the_phrase_keeps_the_data(user: User, engine: Engine) -> None:
    user.find(marker="clear-data").click()
    user.find(marker="clear-data-next").click()
    user.find(marker="clear-data-phrase").type(CONFIRMATION_PHRASE)
    user.find(marker="clear-data-phrase-cancel").click()

    assert portfolio_counts(engine) == FULL


async def test_typing_the_phrase_and_confirming_clears_the_data(user: User, engine: Engine) -> None:
    with user.scope(marker="accounts"):
        await user.should_see("Moje XTB")

    user.find(marker="clear-data").click()
    user.find(marker="clear-data-next").click()
    user.find(marker="clear-data-phrase").type(CONFIRMATION_PHRASE)
    user.find(marker="clear-data-confirm").click()

    await user.should_see("Wyczyszczono dane")
    assert portfolio_counts(engine) == EMPTY
    with user.scope(marker="accounts"):
        await user.should_not_see("Moje XTB")
