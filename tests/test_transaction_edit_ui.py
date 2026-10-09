"""Editing and deleting a Transaction from the Transakcje list (issue #14)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from nicegui.testing.user_interaction import UserInteraction
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import add_transaction, list_transactions
from financial_app.ui.shell import build_shell

NBSP = "\xa0"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def ike(engine: Engine) -> int:
    return add_account(engine, AccountDraft("mBank IKE", "mBank", AccountType.IKE, ("PLN",))).id


@pytest.fixture
def pzu(engine: Engine) -> int:
    asset_class = list_asset_classes(engine)[1]
    return add_instrument(engine, InstrumentDraft("PZU", asset_class.id, "PLN", manual_price=Decimal(60))).id


def _deposit(engine: Engine, account_id: int, amount: str) -> None:
    add_transaction(engine, TransactionDraft(account_id, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(amount)))


def _trade(engine: Engine, account_id: int, instrument_id: int, kind: TransactionType, quantity: str, day: int) -> None:
    add_transaction(
        engine,
        buy_or_sell(account_id, date(2026, 1, day), kind, instrument_id, Decimal(quantity), Decimal(50), Decimal(5)),
    )


def _open_row(user: User, index: int) -> None:
    """Click the ``index``-th row of the Transakcje list (newest first)."""
    rows = sorted(user.find(marker="transaction-row").elements, key=lambda element: element.id)
    UserInteraction(user, {rows[index]}, None).click()


def _error_text(user: User) -> str:
    [error] = user.find(marker="transaction-error").elements
    assert isinstance(error, ui.label)
    text: str = error.text
    return text


async def test_clicking_a_transaction_opens_the_dialog_filled_with_its_data(engine: Engine, ike: int, pzu: int) -> None:
    _trade(engine, ike, pzu, TransactionType.BUY, "10", day=2)

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="transaction-row").click()

        await user.should_see("Edytuj transakcję")
        for marker, value in {
            "transaction-type": "buy",
            "transaction-account": ike,
            "transaction-date": "02.01.2026",
            "transaction-instrument": pzu,
            "transaction-quantity": "10",
            "transaction-price": "50,00",
            "transaction-commission": "5,00",
        }.items():
            [field] = user.find(marker=marker).elements
            assert isinstance(field, (ui.input, ui.select))
            assert field.value == value, marker


async def test_editing_a_buy_changes_the_position_and_cash(engine: Engine, ike: int, pzu: int) -> None:
    _deposit(engine, ike, "1000")
    _trade(engine, ike, pzu, TransactionType.BUY, "10", day=2)

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="transaction-row").click()
        user.find(marker="transaction-quantity").clear().type("4")
        user.find("Zapisz zmiany").click()

        with user.scope(marker="transactions"):
            await user.should_see(f"4 × 50,00{NBSP}zł")
            await user.should_see(f"-205,00{NBSP}zł")
        await user.open("/portfolio")
        with user.scope(marker="portfolio"):
            await user.should_see(f"240,00{NBSP}zł")  # value: 4 × 60
            await user.should_see(f"795,00{NBSP}zł")  # Cash Balance
    assert len(list_transactions(engine)) == 2


async def test_edit_that_uncovers_a_later_sell_is_blocked(engine: Engine, ike: int, pzu: int) -> None:
    _trade(engine, ike, pzu, TransactionType.BUY, "10", day=2)
    _trade(engine, ike, pzu, TransactionType.SELL, "8", day=3)

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="transaction-row").click()  # newest first: the Sell
        user.find(marker="transaction-date").clear().type("01.01.2026")
        user.find("Zapisz zmiany").click()

        assert _error_text(user).startswith("Sprzedaż bez pokrycia")
    assert [t.date.day for t in list_transactions(engine)] == [3, 2]


async def test_deleting_asks_for_confirmation_first(engine: Engine, ike: int) -> None:
    _deposit(engine, ike, "1000")

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="transaction-row").click()
        user.find(marker="delete-transaction").click()

        await user.should_see("Usunąć tę transakcję?")
        assert len(list_transactions(engine)) == 1
        user.find(marker="cancel-delete").click()
        await user.should_see("Edytuj transakcję")
        assert len(list_transactions(engine)) == 1

        user.find(marker="delete-transaction").click()
        user.find(marker="confirm-delete").click()

        with user.scope(marker="transactions"):
            await user.should_see("Brak transakcji")
    assert list_transactions(engine) == []


async def test_deleting_a_buy_that_covers_a_later_sell_is_blocked(engine: Engine, ike: int, pzu: int) -> None:
    _trade(engine, ike, pzu, TransactionType.BUY, "10", day=2)
    _trade(engine, ike, pzu, TransactionType.SELL, "8", day=3)

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        _open_row(user, 1)  # newest first: the Buy
        user.find(marker="delete-transaction").click()
        user.find(marker="confirm-delete").click()

        assert _error_text(user).startswith("Nie można usunąć tej transakcji. Sprzedaż bez pokrycia")
    assert len(list_transactions(engine)) == 2


async def test_deleting_a_deposit_that_leaves_cash_negative_warns(engine: Engine, ike: int, pzu: int) -> None:
    _deposit(engine, ike, "1000")
    _trade(engine, ike, pzu, TransactionType.BUY, "10", day=2)

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        _open_row(user, 1)  # newest first: the Deposit
        user.find(marker="delete-transaction").click()
        user.find(marker="confirm-delete").click()

        await user.should_see("Usunięto, ale Saldo gotówki konta mBank IKE jest ujemne")
    assert len(list_transactions(engine)) == 1
