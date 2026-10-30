"""The transaction dialog's quantity corrections (#278): a save or delete that leaves a Sell uncovered offers, next to
the error, a Buy of the missing units or the Sell trimmed, saved together with the change."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, UserInteraction, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.quantity_corrections import CORRECTION_COMMENT
from financial_app.domain.transactions import TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import add_transaction, list_transactions
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def account(engine: Engine) -> int:
    return add_account(engine, AccountDraft("Giełda", "Krypto", AccountType.REGULAR, ("PLN",))).id


@pytest.fixture
def coin(engine: Engine) -> int:
    asset_class = list_asset_classes(engine)[1]
    return add_instrument(engine, InstrumentDraft("Moneta", asset_class.id, "PLN", manual_price=Decimal(50))).id


def _buy(engine: Engine, account: int, coin: int, quantity: str, day: int) -> None:
    trade = buy_or_sell(account, date(2026, 1, day), TransactionType.BUY, coin, Decimal(quantity), Decimal(40))
    add_transaction(engine, trade)


def _shell(engine: Engine) -> None:
    build_shell(engine, NbpRates(engine, fetch=lambda url: "", today=lambda: date(2026, 1, 8)))


def _choose(user: User, marker: str, option: str) -> None:
    user.find(marker=marker).click()
    UserInteraction(user, set(user.find(marker=marker).elements), option).click()


async def _sell(user: User, quantity: str) -> None:
    """Save, from the "+" dialog, a Sell of ``quantity`` units of Moneta at 50 zł on 07.01.2026."""
    await user.open("/benchmarki")  # the Transakcje list would also offer Moneta to click
    user.find(marker="add-transaction").click()
    _choose(user, "transaction-type", "Sprzedaż")
    user.find(marker="transaction-date").clear().type("07.01.2026")
    _choose(user, "transaction-instrument", "Moneta")
    user.find(marker="transaction-quantity").type(quantity)
    user.find(marker="transaction-price").type("50")
    user.find("Zapisz").click()


async def test_a_sale_short_by_dust_is_saved_with_a_buy_at_cost_zero(engine: Engine, account: int, coin: int) -> None:
    _buy(engine, account, coin, "2", 2)
    async with user_simulation(lambda: _shell(engine)) as user:
        await _sell(user, "2,001")

        await user.should_see("Sprzedaż bez pokrycia")
        with user.scope(marker="transaction-corrections-1"):
            await user.should_see("Brakuje 0,001 szt.")
        [fix] = user.find(marker="transaction-corrections-fix-1", kind=ui.radio).elements
        assert fix.value == "free_buy"
        user.find(marker="transaction-save-corrected").click()

    saved = sorted((t.transaction_type, t.quantity, t.comment) for t in list_transactions(engine))
    assert saved == [
        (TransactionType.BUY, Decimal("0.001"), CORRECTION_COMMENT),
        (TransactionType.BUY, Decimal(2), ""),
        (TransactionType.SELL, Decimal("2.001"), ""),
    ]


async def test_a_large_gap_waits_for_a_fix_and_can_trim_the_sale(engine: Engine, account: int, coin: int) -> None:
    _buy(engine, account, coin, "2", 2)
    async with user_simulation(lambda: _shell(engine)) as user:
        await _sell(user, "2,5")

        await user.should_see(marker="transaction-corrections-large-1")
        [save] = user.find(marker="transaction-save-corrected", kind=ui.button).elements
        assert not save.enabled
        user.find(marker="transaction-corrections-fix-1", kind=ui.radio).elements.pop().set_value("trim")
        user.find(marker="transaction-save-corrected").click()

    sale = next(t for t in list_transactions(engine) if t.transaction_type is TransactionType.SELL)
    assert (sale.quantity, sale.actual_amount) == (Decimal(2), Decimal(125))


async def test_a_delete_uncovering_a_sale_is_saved_with_its_correction(engine: Engine, account: int, coin: int) -> None:
    _buy(engine, account, coin, "0.001", 1)
    _buy(engine, account, coin, "2", 2)
    add_transaction(
        engine, buy_or_sell(account, date(2026, 1, 7), TransactionType.SELL, coin, Decimal("2.001"), Decimal(50))
    )
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        rows = sorted(user.find(marker="transaction-row").elements, key=lambda element: element.id)
        UserInteraction(user, {rows[2]}, None).click()  # newest first: the Buy of 01.01
        user.find(marker="delete-transaction").click()

        await user.should_see("Nie można usunąć tej transakcji")
        user.find(marker="transaction-save-corrected").click()
        await user.should_see(marker="undo-bar")

    buys = sorted((t.date, t.quantity) for t in list_transactions(engine) if t.transaction_type is TransactionType.BUY)
    assert buys == [(date(2026, 1, 2), Decimal(2)), (date(2026, 1, 7), Decimal("0.001"))]
