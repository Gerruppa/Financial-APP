"""Saving, editing and deleting Transactions in SQLite (issues #11, #13, #14)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.lots import InsufficientQuantityError, open_positions
from financial_app.domain.transactions import TransactionDraft, TransactionError, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import (
    add_transaction,
    delete_transaction,
    list_transactions,
    update_transaction,
)


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


@pytest.fixture
def instrument_id(engine: Engine) -> int:
    [first_class, *_] = list_asset_classes(engine)
    return add_instrument(engine, InstrumentDraft("PZU", first_class.id, "PLN")).id


def _trade(account_id: int, instrument_id: int, kind: TransactionType, quantity: str, day: int = 1) -> TransactionDraft:
    return buy_or_sell(
        account_id, date(2026, 1, day), kind, instrument_id, Decimal(quantity), Decimal("45.123"), Decimal(5)
    )


def test_buy_is_listed_with_its_instrument_fields(engine: Engine, account_id: int, instrument_id: int) -> None:
    saved = add_transaction(engine, _trade(account_id, instrument_id, TransactionType.BUY, "0.5"))

    [listed] = list_transactions(engine)
    assert listed == saved
    assert (listed.instrument_id, listed.quantity, listed.price, listed.commission) == (
        instrument_id,
        Decimal("0.5"),
        Decimal("45.123"),
        Decimal(5),
    )
    assert listed.actual_amount == Decimal("27.56")


def test_covered_sell_is_saved(engine: Engine, account_id: int, instrument_id: int) -> None:
    add_transaction(engine, _trade(account_id, instrument_id, TransactionType.BUY, "10", day=1))
    add_transaction(engine, _trade(account_id, instrument_id, TransactionType.SELL, "10", day=2))

    assert len(list_transactions(engine)) == 2


def test_uncovered_sell_is_blocked_and_not_saved(engine: Engine, account_id: int, instrument_id: int) -> None:
    add_transaction(engine, _trade(account_id, instrument_id, TransactionType.BUY, "10", day=5))

    with pytest.raises(InsufficientQuantityError, match="bez pokrycia"):
        add_transaction(engine, _trade(account_id, instrument_id, TransactionType.SELL, "1", day=4))
    assert len(list_transactions(engine)) == 1


def test_trade_of_an_unknown_instrument_is_rejected(engine: Engine, account_id: int) -> None:
    with pytest.raises(TransactionError, match="instrument"):
        add_transaction(engine, _trade(account_id, 999, TransactionType.BUY, "1"))


def test_trade_of_a_foreign_currency_instrument_is_rejected_for_now(engine: Engine, account_id: int) -> None:
    [first_class, *_] = list_asset_classes(engine)
    apple = add_instrument(engine, InstrumentDraft("Apple", first_class.id, "USD")).id

    with pytest.raises(TransactionError, match="w PLN"):
        add_transaction(engine, _trade(account_id, apple, TransactionType.BUY, "1"))


def test_edited_transaction_keeps_its_id_and_takes_the_new_fields(engine: Engine, account_id: int) -> None:
    saved = add_transaction(engine, _deposit(account_id, 5, "100.00"))

    updated = update_transaction(engine, saved.id, _deposit(account_id, 7, "250.00"))

    assert list_transactions(engine) == [updated]
    assert (updated.id, updated.date.day, updated.actual_amount) == (saved.id, 7, Decimal("250.00"))


def test_editing_a_buy_changes_the_position(engine: Engine, account_id: int, instrument_id: int) -> None:
    buy = add_transaction(engine, _trade(account_id, instrument_id, TransactionType.BUY, "10"))

    update_transaction(engine, buy.id, _trade(account_id, instrument_id, TransactionType.BUY, "4"))

    [position] = open_positions(reversed(list_transactions(engine)))
    assert position.quantity == 4


def test_edit_keeps_the_same_day_entry_order(engine: Engine, account_id: int, instrument_id: int) -> None:
    buy = add_transaction(engine, _trade(account_id, instrument_id, TransactionType.BUY, "10", day=1))
    add_transaction(engine, _trade(account_id, instrument_id, TransactionType.SELL, "5", day=1))

    update_transaction(engine, buy.id, _trade(account_id, instrument_id, TransactionType.BUY, "6", day=1))

    [position] = open_positions(reversed(list_transactions(engine)))
    assert position.quantity == 1


def test_edit_that_uncovers_a_later_sell_is_blocked(engine: Engine, account_id: int, instrument_id: int) -> None:
    buy = add_transaction(engine, _trade(account_id, instrument_id, TransactionType.BUY, "10", day=1))
    add_transaction(engine, _trade(account_id, instrument_id, TransactionType.SELL, "8", day=2))

    with pytest.raises(InsufficientQuantityError, match="bez pokrycia"):
        update_transaction(engine, buy.id, _trade(account_id, instrument_id, TransactionType.BUY, "5", day=1))
    assert [t.quantity for t in list_transactions(engine)] == [Decimal(8), Decimal(10)]


def test_moving_a_buy_to_another_instrument_checks_the_old_one(
    engine: Engine, account_id: int, instrument_id: int
) -> None:
    [first_class, *_] = list_asset_classes(engine)
    other = add_instrument(engine, InstrumentDraft("KGHM", first_class.id, "PLN")).id
    buy = add_transaction(engine, _trade(account_id, instrument_id, TransactionType.BUY, "10", day=1))
    add_transaction(engine, _trade(account_id, instrument_id, TransactionType.SELL, "8", day=2))

    with pytest.raises(InsufficientQuantityError):
        update_transaction(engine, buy.id, _trade(account_id, other, TransactionType.BUY, "10", day=1))


def test_moving_a_buy_to_another_account_checks_the_old_one(
    engine: Engine, account_id: int, instrument_id: int
) -> None:
    other = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id
    buy = add_transaction(engine, _trade(account_id, instrument_id, TransactionType.BUY, "10", day=1))
    add_transaction(engine, _trade(account_id, instrument_id, TransactionType.SELL, "8", day=2))

    with pytest.raises(InsufficientQuantityError):
        update_transaction(engine, buy.id, _trade(other, instrument_id, TransactionType.BUY, "10", day=1))


def test_turning_a_buy_into_a_deposit_checks_the_old_position(
    engine: Engine, account_id: int, instrument_id: int
) -> None:
    buy = add_transaction(engine, _trade(account_id, instrument_id, TransactionType.BUY, "10", day=1))
    add_transaction(engine, _trade(account_id, instrument_id, TransactionType.SELL, "8", day=2))

    with pytest.raises(InsufficientQuantityError):
        update_transaction(engine, buy.id, _deposit(account_id, 1))


def test_editing_an_unknown_transaction_is_rejected(engine: Engine, account_id: int) -> None:
    with pytest.raises(TransactionError, match="nie istnieje"):
        update_transaction(engine, 999, _deposit(account_id, 1))


def test_deleted_transaction_is_gone(engine: Engine, account_id: int) -> None:
    kept = add_transaction(engine, _deposit(account_id, 1))
    gone = add_transaction(engine, _deposit(account_id, 2))

    delete_transaction(engine, gone.id)

    assert list_transactions(engine) == [kept]


def test_deleting_a_buy_that_covers_a_later_sell_is_blocked(
    engine: Engine, account_id: int, instrument_id: int
) -> None:
    buy = add_transaction(engine, _trade(account_id, instrument_id, TransactionType.BUY, "10", day=1))
    add_transaction(engine, _trade(account_id, instrument_id, TransactionType.SELL, "8", day=2))

    with pytest.raises(InsufficientQuantityError, match="bez pokrycia"):
        delete_transaction(engine, buy.id)
    assert len(list_transactions(engine)) == 2


def test_deleting_a_sell_is_allowed(engine: Engine, account_id: int, instrument_id: int) -> None:
    add_transaction(engine, _trade(account_id, instrument_id, TransactionType.BUY, "10", day=1))
    sell = add_transaction(engine, _trade(account_id, instrument_id, TransactionType.SELL, "8", day=2))

    delete_transaction(engine, sell.id)

    [position] = open_positions(reversed(list_transactions(engine)))
    assert position.quantity == 10
