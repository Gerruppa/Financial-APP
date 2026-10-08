"""Ustawienia > Konta (issue #10): the user adds, edits and deactivates Accounts, run without a browser."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.persistence.accounts import add_account, list_accounts
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


def _fill_form(user: User, **fields: str) -> None:
    for marker, text in fields.items():
        user.find(marker=marker).clear().type(text)


def _choose_account_type(user: User, label: str) -> None:
    """Pick from the Typ konta select; call it before typing text containing ``label`` into the inputs above it,
    because ``find`` by text clicks the first (lowest-id) element whose content matches."""
    user.find(marker="account-type").click()
    user.find(label).click()


async def test_settings_list_shows_saved_accounts(engine: Engine) -> None:
    add_account(engine, AccountDraft("XTB", "X-Trade Brokers", AccountType.REGULAR, ("PLN", "USD")))

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")

        with user.scope(marker="accounts"):
            await user.should_see("XTB")
            await user.should_see("X-Trade Brokers")
            await user.should_see("PLN, USD")


async def test_user_adds_an_account(user: User, engine: Engine) -> None:
    user.find("Dodaj konto").click()
    _choose_account_type(user, "IKE")
    _fill_form(user, **{"account-name": "XTB IKE", "account-broker": "XTB", "account-currencies": "PLN, usd"})
    user.find(marker="account-fee").type("0,5")
    user.find(marker="account-exclude-fx").click()
    user.find("Zapisz").click()

    with user.scope(marker="accounts"):
        await user.should_see("XTB IKE")
        await user.should_see("0,50\xa0%")
    [saved] = list_accounts(engine)
    assert saved.account_type is AccountType.IKE
    assert saved.cash_currencies == ("PLN", "USD")
    assert saved.exclude_fx_result


async def test_choosing_oki_shows_the_placeholder_note(user: User) -> None:
    user.find("Dodaj konto").click()
    _choose_account_type(user, "OKI")

    await user.should_see("po uchwaleniu przepisów")


async def test_duplicate_name_is_reported_and_not_saved(engine: Engine) -> None:
    add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",)))

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find("Dodaj konto").click()
        _fill_form(user, **{"account-name": "xtb", "account-currencies": "PLN"})
        user.find("Zapisz").click()

        await user.should_see("już istnieje")
    assert len(list_accounts(engine)) == 1


async def test_user_edits_and_deactivates_an_account(engine: Engine) -> None:
    add_account(engine, AccountDraft("mBank", "mBank", AccountType.REGULAR, ("PLN",)))

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-account").click()
        _fill_form(user, **{"account-name": "mBank eMakler"})
        user.find(marker="account-active").click()
        user.find("Zapisz").click()

        with user.scope(marker="accounts"):
            await user.should_see("mBank eMakler")
            await user.should_see("nieaktywne")
    [saved] = list_accounts(engine)
    assert saved.name == "mBank eMakler"
    assert not saved.active
