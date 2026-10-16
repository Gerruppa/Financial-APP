"""Saving an Early Redemption (L-5, ADR-0007): a Sell naming its Lot and the tax withheld, kept across a reload, and
the Lot's Buy guarded while a redemption names it."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.lots import LotNotHeldError, open_positions
from financial_app.domain.transactions import Transaction, TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import (
    add_transaction,
    delete_transaction,
    list_transactions,
    transactions_in_entry_order,
    update_transaction,
)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def ids(engine: Engine) -> tuple[int, int]:
    account = add_account(engine, AccountDraft("PKO Obligacje", "PKO BP", AccountType.BONDS, ("PLN",))).id
    bond_class = next(c for c in list_asset_classes(engine) if c.name == "Obligacje skarbowe polskie")
    edo = add_instrument(engine, InstrumentDraft("EDO0534", bond_class.id, "PLN")).id
    return account, edo


def _buy(engine: Engine, ids: tuple[int, int], day: date) -> Transaction:
    account, edo = ids
    return add_transaction(engine, buy_or_sell(account, day, TransactionType.BUY, edo, Decimal(10), Decimal(100)))


def _redemption(ids: tuple[int, int], lot_id: int, quantity: int = 4) -> TransactionDraft:
    account, edo = ids
    return buy_or_sell(
        account,
        date(2025, 10, 8),
        TransactionType.SELL,
        edo,
        Decimal(quantity),
        Decimal("108.67"),
        Decimal("8.00"),
        withholding_tax=Decimal("5.08"),
        lot_id=lot_id,
    )


def test_a_redemption_keeps_its_lot_and_tax(engine: Engine, ids: tuple[int, int]) -> None:
    first, second = _buy(engine, ids, date(2024, 5, 22)), _buy(engine, ids, date(2025, 3, 3))

    saved = add_transaction(engine, _redemption(ids, second.id))

    [reloaded] = [t for t in list_transactions(engine) if t.id == saved.id]
    assert (reloaded.lot_id, reloaded.withholding_tax, reloaded.actual_amount) == (
        second.id,
        Decimal("5.08"),
        Decimal("421.60"),
    )
    [position] = open_positions(transactions_in_entry_order(engine))
    assert [(lot.opened_by, lot.quantity) for lot in position.lots] == [
        (first.id, Decimal(10)),
        (second.id, Decimal(6)),
    ]


def test_the_named_lots_buy_cannot_go_while_the_redemption_names_it(engine: Engine, ids: tuple[int, int]) -> None:
    _buy(engine, ids, date(2024, 5, 22))
    second = _buy(engine, ids, date(2025, 3, 3))
    add_transaction(engine, _redemption(ids, second.id))

    with pytest.raises(LotNotHeldError):
        delete_transaction(engine, second.id)


def test_editing_the_named_lots_buy_keeps_its_name(engine: Engine, ids: tuple[int, int]) -> None:
    account, edo = ids
    bought = _buy(engine, ids, date(2024, 5, 22))
    add_transaction(engine, _redemption(ids, bought.id))

    cheaper = buy_or_sell(account, date(2024, 5, 22), TransactionType.BUY, edo, Decimal(10), Decimal("99.9"))
    update_transaction(engine, bought.id, cheaper)

    [position] = open_positions(transactions_in_entry_order(engine))
    assert (position.quantity, position.lots[0].opened_by) == (Decimal(6), bought.id)
