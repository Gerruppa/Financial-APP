"""The negative PLN cash warning's fix (#267): "Dodaj wpłaty uzupełniające" opens the proposed Deposits per Account,
and saves the ticked ones."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.transactions import TransactionDraft, TransactionType, lowest_cash_balance
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.transactions import add_transaction, list_transactions
from financial_app.sources.transaction_saving import COVERING_COMMENT
from financial_app.ui.shell import build_shell

NBSP = "\xa0"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def xtb(engine: Engine) -> int:
    account = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id
    add_transaction(engine, TransactionDraft(account, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(100)))
    return account


async def _withdraw_150(user: User) -> None:
    """Save, from the "+" dialog, a Withdrawal that takes the Account's cash to -50 zł."""
    await user.open("/transakcje")
    user.find(marker="add-transaction").click()
    user.find(marker="transaction-type").click()
    user.find("Wypłata").click()
    user.find(marker="transaction-date").clear().type("05.10.2026")
    user.find(marker="transaction-amount").type("150")
    user.find("Zapisz").click()
    await user.should_see("Saldo gotówki konta XTB jest ujemne")


def _window_open(user: User) -> bool:
    """A closed dialog stays in the simulated page (it is deleted on the browser's "hide"), so ask the dialog."""
    [window] = user.find(marker="covering-window").elements
    return bool(next(a for a in window.ancestors() if isinstance(a, ui.dialog)).value)


async def test_the_action_saves_the_deposit_that_brings_the_cash_back_to_zero(engine: Engine, xtb: int) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await _withdraw_150(user)
        user.find(marker="covering-button").click()

        with user.scope(marker="covering-window"):
            await user.should_see(f"XTB: dodaj 1 wpłatę, razem 50,00{NBSP}zł")
            await user.should_see(f"05.10.2026: 50,00{NBSP}zł")
        user.find(marker="covering-save").click()

        assert not _window_open(user)
        await user.should_not_see(marker="covering-bar")
        with user.scope(marker="transactions"):
            await user.should_see(f"+50,00{NBSP}zł")
    deposit = list_transactions(engine)[0]
    assert (deposit.date, deposit.transaction_type, deposit.actual_amount, deposit.comment) == (
        date(2026, 10, 5),
        TransactionType.DEPOSIT,
        Decimal(50),
        COVERING_COMMENT,
    )
    assert lowest_cash_balance(list_transactions(engine), xtb, start=date(2026, 1, 2)) == 0


async def test_an_unticked_account_gets_no_deposits(engine: Engine, xtb: int) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await _withdraw_150(user)
        user.find(marker="covering-button").click()
        user.find(marker=f"covering-account-{xtb}").click()
        user.find(marker="covering-save").click()

        assert not _window_open(user)
    assert len(list_transactions(engine)) == 2


async def test_a_save_within_the_cash_offers_no_deposits(engine: Engine, xtb: int) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="add-transaction").click()
        user.find(marker="transaction-amount").type("10")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see(f"+10,00{NBSP}zł")
        await user.should_not_see(marker="covering-bar")
