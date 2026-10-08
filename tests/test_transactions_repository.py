"""Saving Transactions in SQLite (issue #11)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.transactions import TransactionDraft, TransactionError, TransactionType
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.transactions import add_transaction, list_transactions


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    return tmp_path / "app.sqlite3"


@pytest.fixture
def engine(db_file: Path) -> Engine:
    return init_db(db_file)


@pytest.fixture
def account_id(engine: Engine) -> int:
    return add_account(engine, AccountDraft("mBank", "mBank", AccountType.REGULAR, ("PLN",))).id


def _deposit(account_id: int, day: int, amount: str = "100.00") -> TransactionDraft:
    return TransactionDraft(account_id, date(2026, 1, day), TransactionType.DEPOSIT, Decimal(amount), "pensja")


def test_added_transaction_is_listed_with_all_its_fields(engine: Engine, account_id: int) -> None:
    saved = add_transaction(engine, _deposit(account_id, 5, "1234.56"))

    [listed] = list_transactions(engine)
    assert listed == saved
    assert listed.account_id == account_id
    assert listed.date == date(2026, 1, 5)
    assert listed.transaction_type is TransactionType.DEPOSIT
    assert listed.actual_amount == Decimal("1234.56")
    assert listed.comment == "pensja"


def test_transactions_are_listed_newest_first(engine: Engine, account_id: int) -> None:
    add_transaction(engine, _deposit(account_id, 1))
    add_transaction(engine, _deposit(account_id, 20))
    add_transaction(engine, _deposit(account_id, 10))

    assert [t.date.day for t in list_transactions(engine)] == [20, 10, 1]


def test_same_day_transactions_keep_entry_order_newest_first(engine: Engine, account_id: int) -> None:
    first = add_transaction(engine, _deposit(account_id, 1))
    second = add_transaction(engine, _deposit(account_id, 1))

    assert [t.id for t in list_transactions(engine)] == [second.id, first.id]


def test_transactions_survive_a_restart(db_file: Path, engine: Engine, account_id: int) -> None:
    add_transaction(engine, _deposit(account_id, 1))
    engine.dispose()

    assert len(list_transactions(init_db(db_file))) == 1


def test_transaction_on_an_unknown_account_is_rejected(engine: Engine) -> None:
    with pytest.raises(TransactionError, match="konto"):
        add_transaction(engine, _deposit(999, 1))
