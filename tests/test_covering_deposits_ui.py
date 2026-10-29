"""The negative PLN cash warning's fix (#267): "Dodaj wpłaty uzupełniające" opens the proposed Deposits per Account,
and saves the ticked ones; undoing a delete they covered explains each difference first."""

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from nicegui.testing.user_interaction import UserInteraction
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.transactions import COVERING_COMMENT, TransactionDraft, TransactionType, lowest_cash_balance
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.transactions import add_transaction, list_transactions
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


def _open_row(user: User, index: int) -> None:
    """Click the ``index``-th row of the Transakcje list (newest first)."""
    rows = sorted(user.find(marker="transaction-row").elements, key=lambda element: element.id)
    UserInteraction(user, {rows[index]}, None).click()


def _add(engine: Engine, account: int, day: int, kind: TransactionType, amount: int) -> None:
    add_transaction(engine, TransactionDraft(account, date(2026, 1, day), kind, Decimal(amount)))


async def _delete_and_cover(user: User, row: int) -> None:
    """Delete the ``row``-th Transaction, which takes the cash below zero, then save its covering Deposit."""
    await user.open("/transakcje")
    _open_row(user, row)
    user.find(marker="delete-transaction").click()
    await user.should_see(marker="undo-bar")
    user.find(marker="covering-button").click()
    user.find(marker="covering-save").click()
    await user.should_see(marker="undo-bar")


async def test_undoing_a_delete_after_covering_it_explains_and_can_drop_the_deposits(engine: Engine, xtb: int) -> None:
    _add(engine, xtb, 3, TransactionType.WITHDRAWAL, 60)

    async with user_simulation(lambda: build_shell(engine)) as user:
        await _delete_and_cover(user, 1)  # newest first: the Deposit of 02.01
        user.find(marker="undo-button").click()

        with user.scope(marker="undo-window"):
            await user.should_see(f"Przywrócę: 02.01.2026 · XTB · Wpłata · 100,00{NBSP}zł")
            await user.should_see(f"03.01.2026: 60,00{NBSP}zł")
            await user.should_see(f"o 60,00{NBSP}zł wyższa niż przed usunięciem")
        user.find(marker="undo-drop-covering").click()

        with user.scope(marker="transactions"):
            await user.should_see(f"+100,00{NBSP}zł")
    assert sorted(t.actual_amount for t in list_transactions(engine)) == [Decimal(60), Decimal(100)]
    assert [t.comment for t in list_transactions(engine)] == ["", ""]


async def test_undoing_a_delete_can_keep_the_covering_deposits(engine: Engine, xtb: int) -> None:
    _add(engine, xtb, 3, TransactionType.WITHDRAWAL, 60)

    async with user_simulation(lambda: build_shell(engine)) as user:
        await _delete_and_cover(user, 1)
        user.find(marker="undo-button").click()
        user.find(marker="undo-restore").click()

        with user.scope(marker="transactions"):
            await user.should_see(f"+100,00{NBSP}zł")
    assert sorted(t.actual_amount for t in list_transactions(engine)) == [Decimal(60), Decimal(60), Decimal(100)]


async def test_a_covering_deposit_that_took_the_deleted_place_must_go_with_the_undo(engine: Engine, xtb: int) -> None:
    _add(engine, xtb, 3, TransactionType.WITHDRAWAL, 120)
    _add(engine, xtb, 1, TransactionType.DEPOSIT, 50)  # the newest id, which SQLite hands on once freed

    async with user_simulation(lambda: build_shell(engine)) as user:
        await _delete_and_cover(user, 2)  # newest first: the Deposit of 01.01
        user.find(marker="undo-button").click()

        with user.scope(marker="undo-window"):
            await user.should_see("zajęła jej numer")
        [keep] = user.find(marker="undo-restore").elements
        assert isinstance(keep, ui.button)
        assert not keep.enabled
        user.find(marker="undo-drop-covering").click()

        with user.scope(marker="transactions"):
            await user.should_see(f"+50,00{NBSP}zł")
    assert sorted(t.actual_amount for t in list_transactions(engine)) == [Decimal(50), Decimal(100), Decimal(120)]


async def test_the_undo_bar_waits_while_the_covering_window_is_open(
    engine: Engine, xtb: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bar outlasts its time while the window is open, then gets it afresh, to undo once the Deposits are in."""
    monkeypatch.setattr("financial_app.ui.undo.UNDO_SECONDS", 0.5)
    monkeypatch.setattr("financial_app.ui.undo.HOLD_CHECK_SECONDS", 0.1)
    _add(engine, xtb, 3, TransactionType.WITHDRAWAL, 60)

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        _open_row(user, 1)
        user.find(marker="delete-transaction").click()
        user.find(marker="covering-button").click()
        await asyncio.sleep(1.0)  # twice the bar's time
        await user.should_see(marker="undo-bar")

        user.find(marker="covering-save").click()
        await asyncio.sleep(0.2)
        await user.should_see(marker="undo-bar")

        await asyncio.sleep(1.2)
        await user.should_not_see(marker="undo-bar")
