"""The first-run window (#270): opened on a database with no Accounts, dismissed once for good, reopened from
Ustawienia > Konta and the header's chip (#288), its steps' actions and which of them are done."""

from collections.abc import AsyncIterator, Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.transactions import TransactionDraft, TransactionType
from financial_app.persistence.accounts import add_account, list_accounts
from financial_app.persistence.db import init_db
from financial_app.persistence.settings import FIRST_RUN_CHIP_HIDDEN, FIRST_RUN_DISMISSED, load_setting
from financial_app.persistence.transactions import add_transaction, list_transactions
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def shell(engine: Engine) -> Callable[[], None]:
    return lambda: build_shell(engine, NbpRates(engine, fetch=lambda url: None), offer_first_run=True)


@pytest.fixture
async def user(engine: Engine) -> AsyncIterator[User]:
    async with user_simulation(shell(engine)) as user:
        await user.open("/")
        yield user


def window_open(user: User) -> bool:
    [card] = user.find(marker="first-run-wizard").elements
    assert card.parent_slot is not None
    dialog = card.parent_slot.parent
    assert isinstance(dialog, ui.dialog)
    return bool(dialog.value)


def settings_section(user: User) -> object:
    """The Ustawienia section on screen: every section is drawn at once, so a marker alone says nothing."""
    [tabs] = user.find(ui.tabs).elements
    assert isinstance(tabs, ui.tabs)
    return tabs.value


async def test_it_opens_on_a_database_with_no_accounts(user: User) -> None:
    await user.should_see(marker="first-run-step-1")
    await user.should_see("dane zostają na tym komputerze")


async def test_it_does_not_open_once_an_account_exists(engine: Engine) -> None:
    add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN",)))
    async with user_simulation(shell(engine)) as user:
        await user.open("/")

        await user.should_not_see(marker="first-run-step-1")


async def test_closing_it_is_remembered_and_it_reopens_from_ustawienia(engine: Engine, user: User) -> None:
    await user.should_see(marker="first-run-step-1")
    user.find(marker="first-run-close").click()

    assert not window_open(user)
    assert load_setting(engine, FIRST_RUN_DISMISSED) == "1"
    async with user_simulation(shell(engine)) as again:
        await again.open("/ustawienia")
        await again.should_not_see(marker="first-run-step-1")

        again.find(marker="first-run-open").click()

        await again.should_see(marker="first-run-step-1")


async def test_the_accounts_step_adds_an_account(engine: Engine, user: User) -> None:
    user.find(marker="first-run-next").click()
    await user.should_see(marker="first-run-step-2")
    await user.should_see("IKZE")
    await user.should_see("Nie dodano jeszcze żadnego konta")

    user.find(marker="first-run-add-account").click()
    user.find(marker="account-name").type("Moje IKE")
    user.find("Zapisz").click()

    assert [account.name for account in list_accounts(engine)] == ["Moje IKE"]
    with user.scope(marker="first-run-accounts"):
        await user.should_see("Moje IKE")
    await user.should_see(marker="first-run-step-2")


async def test_an_account_added_from_ustawienia_shows_in_konta(user: User) -> None:
    user.find(marker="first-run-close").click()
    await user.open("/ustawienia")
    user.find(marker="first-run-open").click()
    user.find(marker="first-run-next").click()

    user.find(marker="first-run-add-account").click()
    user.find(marker="account-name").type("Maklerskie")
    user.find("Zapisz").click()

    with user.scope(marker="accounts"):
        await user.should_see("Maklerskie")


async def test_the_history_step_goes_to_the_import_section(user: User) -> None:
    user.find(marker="first-run-next").click()
    user.find(marker="first-run-next").click()
    await user.should_see(marker="first-run-step-3")

    user.find(marker="first-run-import").click()

    await user.should_see(marker="xtb-open")
    assert settings_section(user) == "import"
    assert not window_open(user)


async def test_the_history_step_opens_the_transaction_form(user: User) -> None:
    for _ in range(2):
        user.find(marker="first-run-next").click()

    user.find(marker="first-run-add-transaction").click()

    await user.should_see("Nowa transakcja")


async def test_the_prices_step_goes_to_the_instruments_from_ustawienia_too(user: User) -> None:
    """On Ustawienia already, the button switches the section on screen."""
    user.find(marker="first-run-close").click()
    await user.open("/ustawienia")
    user.find(marker="first-run-open").click()
    for _ in range(3):
        user.find(marker="first-run-next").click()
    await user.should_see(marker="first-run-step-4")
    await user.should_see("Yahoo")

    user.find(marker="first-run-instruments").click()

    await user.should_see(marker="instruments")
    assert settings_section(user) == "instruments"


async def test_the_last_step_says_where_things_are_and_how_to_reopen_it(user: User) -> None:
    for _ in range(4):
        user.find(marker="first-run-next").click()

    await user.should_see(marker="first-run-step-5")
    await user.should_see("Pierwsze kroki")
    await user.should_not_see(marker="first-run-next")


def ike(engine: Engine) -> int:
    return add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN",))).id


def deposit(engine: Engine, account_id: int) -> None:
    add_transaction(engine, TransactionDraft(account_id, date(2026, 1, 5), TransactionType.DEPOSIT, Decimal("100")))


async def test_the_step_list_ticks_the_steps_done(engine: Engine, user: User) -> None:
    await user.should_see(marker="first-run-goto-2")
    await user.should_not_see(marker="first-run-done-2")
    user.find(marker="first-run-goto-2").click()
    await user.should_see(marker="first-run-step-2")

    user.find(marker="first-run-add-account").click()
    user.find(marker="account-name").type("Moje IKE")
    user.find("Zapisz").click()

    await user.should_see(marker="first-run-done-2")
    await user.should_not_see(marker="first-run-done-3")


async def test_it_reopens_on_the_first_step_not_done(engine: Engine) -> None:
    ike(engine)
    async with user_simulation(shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="first-run-open").click()

        await user.should_see(marker="first-run-step-3")
        await user.should_see(marker="first-run-done-2")


async def test_the_header_chip_counts_the_steps_and_opens_the_window(engine: Engine) -> None:
    ike(engine)
    async with user_simulation(shell(engine)) as user:
        await user.open("/")
        await user.should_not_see(marker="first-run-step-1")

        await user.should_see("Pierwsze kroki 1/3")
        user.find(marker="first-run-chip-open").click()

        await user.should_see(marker="first-run-step-3")


async def test_the_chip_goes_once_every_step_is_done(engine: Engine) -> None:
    """A Deposit holds no Instrument, so nothing waits for a price."""
    deposit(engine, ike(engine))
    async with user_simulation(shell(engine)) as user:
        await user.open("/")

        await user.should_not_see(marker="first-run-chip")


async def test_closing_the_chip_is_remembered(engine: Engine, user: User) -> None:
    user.find(marker="first-run-close").click()
    await user.should_see("Pierwsze kroki 0/3")

    user.find(marker="first-run-chip-hide").click()

    await user.should_not_see(marker="first-run-chip")
    assert load_setting(engine, FIRST_RUN_CHIP_HIDDEN) == "1"
    async with user_simulation(shell(engine)) as again:
        await again.open("/")
        await again.should_not_see(marker="first-run-chip")


async def test_a_transaction_saved_from_the_window_brings_it_back(engine: Engine) -> None:
    ike(engine)
    async with user_simulation(shell(engine)) as user:
        await user.open("/")
        user.find(marker="first-run-chip-open").click()
        await user.should_see(marker="first-run-step-3")

        user.find(marker="first-run-add-transaction").click()
        user.find(marker="transaction-amount").type("100")
        user.find("Zapisz").click()

        assert len(list_transactions(engine)) == 1
        assert window_open(user)
        await user.should_see(marker="first-run-done-3")
        # A Deposit holds no Instrument, so with it every step is done
        await user.should_not_see(marker="first-run-chip")
