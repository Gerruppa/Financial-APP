"""Saving Splits, Cash Transfers and Security Transfers in SQLite (issue #19)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.lots import InsufficientQuantityError, SplitBeforeFirstBuyError, open_positions
from financial_app.domain.transactions import (
    SplitRatio,
    TransactionError,
    TransactionType,
    buy_or_sell,
    cash_balances,
    cash_transfer,
    security_transfer,
    split,
)
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
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def ike(engine: Engine) -> int:
    return add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id


@pytest.fixture
def xtb(engine: Engine) -> int:
    return add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id


@pytest.fixture
def pzu(engine: Engine) -> int:
    asset_class = list_asset_classes(engine)[1]
    return add_instrument(engine, InstrumentDraft("PZU", asset_class.id, "PLN")).id


@pytest.fixture
def apple(engine: Engine) -> int:
    asset_class = list_asset_classes(engine)[2]
    return add_instrument(engine, InstrumentDraft("Apple", asset_class.id, "USD")).id


def test_split_is_saved_with_its_ratio_and_rescales_the_position(engine: Engine, ike: int, pzu: int) -> None:
    add_transaction(engine, buy_or_sell(ike, date(2026, 1, 1), TransactionType.BUY, pzu, Decimal(10), Decimal(50)))

    saved = add_transaction(engine, split(ike, date(2026, 1, 2), pzu, SplitRatio(5, 1), "split 5:1"))

    [reread, _] = list_transactions(engine)
    assert reread == saved
    assert (reread.split_ratio, reread.instrument_id, reread.actual_amount) == (SplitRatio(5, 1), pzu, Decimal(0))
    [position] = open_positions(reversed(list_transactions(engine)))
    assert (position.quantity, position.cost) == (Decimal(50), Decimal(500))


def test_split_before_the_first_buy_is_not_saved(engine: Engine, ike: int, pzu: int) -> None:
    add_transaction(engine, buy_or_sell(ike, date(2026, 1, 5), TransactionType.BUY, pzu, Decimal(10), Decimal(50)))

    with pytest.raises(SplitBeforeFirstBuyError):
        add_transaction(engine, split(ike, date(2026, 1, 2), pzu, SplitRatio(2, 1)))
    assert len(list_transactions(engine)) == 1


def test_deleting_the_buy_under_a_split_is_blocked(engine: Engine, ike: int, pzu: int) -> None:
    buy = add_transaction(
        engine, buy_or_sell(ike, date(2026, 1, 1), TransactionType.BUY, pzu, Decimal(10), Decimal(50))
    )
    add_transaction(engine, split(ike, date(2026, 1, 2), pzu, SplitRatio(2, 1)))

    with pytest.raises(SplitBeforeFirstBuyError):
        delete_transaction(engine, buy.id)


def test_security_transfer_is_saved_and_the_target_account_can_sell_the_units(
    engine: Engine, ike: int, xtb: int, pzu: int
) -> None:
    add_transaction(engine, buy_or_sell(ike, date(2026, 1, 1), TransactionType.BUY, pzu, Decimal(10), Decimal(50)))
    transfer = add_transaction(engine, security_transfer(ike, date(2026, 1, 3), xtb, pzu, Decimal(10)))

    add_transaction(engine, buy_or_sell(xtb, date(2026, 1, 4), TransactionType.SELL, pzu, Decimal(4), Decimal(60)))

    assert list_transactions(engine)[1] == transfer
    assert transfer.target_account_id == xtb
    [position] = open_positions(reversed(list_transactions(engine)))
    assert (position.account_id, position.quantity, position.lots[0].date) == (xtb, Decimal(6), date(2026, 1, 1))


def test_deleting_a_transfer_a_later_sell_needs_is_blocked(engine: Engine, ike: int, xtb: int, pzu: int) -> None:
    add_transaction(engine, buy_or_sell(ike, date(2026, 1, 1), TransactionType.BUY, pzu, Decimal(10), Decimal(50)))
    transfer = add_transaction(engine, security_transfer(ike, date(2026, 1, 3), xtb, pzu, Decimal(10)))
    add_transaction(engine, buy_or_sell(xtb, date(2026, 1, 4), TransactionType.SELL, pzu, Decimal(4), Decimal(60)))

    with pytest.raises(InsufficientQuantityError):
        delete_transaction(engine, transfer.id)
    with pytest.raises(InsufficientQuantityError):
        update_transaction(engine, transfer.id, security_transfer(ike, date(2026, 1, 3), xtb, pzu, Decimal(3)))


def test_transfer_of_more_than_held_is_not_saved(engine: Engine, ike: int, xtb: int, pzu: int) -> None:
    add_transaction(engine, buy_or_sell(ike, date(2026, 1, 1), TransactionType.BUY, pzu, Decimal(10), Decimal(50)))

    with pytest.raises(InsufficientQuantityError):
        add_transaction(engine, security_transfer(ike, date(2026, 1, 3), xtb, pzu, Decimal(11)))


def test_foreign_instrument_moves_and_splits_without_an_nbp_rate(
    engine: Engine, ike: int, xtb: int, apple: int
) -> None:
    rate = NbpRate("USD", Decimal("3.6"), date(2025, 12, 31), "252/A/NBP/2025")
    buy = buy_or_sell(ike, date(2026, 1, 2), TransactionType.BUY, apple, Decimal(2), Decimal(100), nbp_rate=rate)
    add_transaction(engine, buy)

    add_transaction(engine, security_transfer(ike, date(2026, 1, 3), xtb, apple, Decimal(2)))
    add_transaction(engine, split(xtb, date(2026, 1, 4), apple, SplitRatio(4, 1)))

    [position] = open_positions(reversed(list_transactions(engine)))
    assert (position.account_id, position.quantity, position.cost) == (xtb, Decimal(8), Decimal(720))


def test_cash_transfer_is_saved_and_moves_the_balance(engine: Engine, ike: int, xtb: int) -> None:
    saved = add_transaction(engine, cash_transfer(ike, date(2026, 1, 3), xtb, Decimal(250), "na XTB"))

    assert list_transactions(engine) == [saved]
    assert cash_balances(list_transactions(engine)) == {ike: Decimal(-250), xtb: Decimal(250)}


def test_transfer_to_a_missing_account_is_not_saved(engine: Engine, ike: int) -> None:
    with pytest.raises(TransactionError, match="docelowe"):
        add_transaction(engine, cash_transfer(ike, date(2026, 1, 3), 999, Decimal(250)))
