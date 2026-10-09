"""PLN Buys and Sells end to end (issue #13): "+" dialog, Transakcje list, Positions in Portfolio."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
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


def _instrument(engine: Engine, name: str, manual_price: str | None = None) -> int:
    asset_class = list_asset_classes(engine)[1]
    price = None if manual_price is None else Decimal(manual_price)
    return add_instrument(engine, InstrumentDraft(name, asset_class.id, "PLN", manual_price=price)).id


@pytest.fixture
def pzu(engine: Engine) -> int:
    return _instrument(engine, "PZU", manual_price="60")


def _deposit(engine: Engine, account_id: int, amount: str) -> None:
    add_transaction(engine, TransactionDraft(account_id, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(amount)))


def _buy(engine: Engine, account_id: int, instrument_id: int, quantity: str, price: str, fee: str = "0") -> None:
    draft = buy_or_sell(
        account_id,
        date(2026, 1, 2),
        TransactionType.BUY,
        instrument_id,
        Decimal(quantity),
        Decimal(price),
        Decimal(fee),
    )
    add_transaction(engine, draft)


def _save_trade(
    user: User, type_label: str, instrument: str, quantity: str, price: str, fee: str = "", day: str = "05.10.2026"
) -> None:
    user.find(marker="add-transaction").click()
    user.find(marker="transaction-type").click()
    user.find(type_label).click()
    user.find(marker="transaction-instrument").click()
    user.find(instrument).click()
    user.find(marker="transaction-date").clear().type(day)
    user.find(marker="transaction-quantity").type(quantity)
    user.find(marker="transaction-price").type(price)
    if fee:
        user.find(marker="transaction-commission").type(fee)
    user.find("Zapisz").click()


async def test_buy_from_plus_dialog_appears_in_transakcje(engine: Engine, ike: int, pzu: int) -> None:
    _deposit(engine, ike, "1000")

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")

        _save_trade(user, "Zakup", "PZU", "10", "45,5", fee="5")

        with user.scope(marker="transactions"):
            await user.should_see("Zakup")
            await user.should_see("PZU")
            await user.should_see(f"10 × 45,50{NBSP}zł")
            await user.should_see(f"-460,00{NBSP}zł")
        await user.should_not_see("jest ujemne")
    [buy, _] = list_transactions(engine)
    assert (buy.instrument_id, buy.quantity, buy.price, buy.commission) == (
        pzu,
        Decimal(10),
        Decimal("45.5"),
        Decimal(5),
    )


async def test_buy_without_enough_cash_saves_with_a_warning(engine: Engine, ike: int, pzu: int) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")

        _save_trade(user, "Zakup", "PZU", "10", "50")

        await user.should_see("Saldo gotówki konta mBank IKE jest ujemne")
    assert len(list_transactions(engine)) == 1


async def test_uncovered_sell_is_blocked_with_a_clear_message(engine: Engine, ike: int, pzu: int) -> None:
    _buy(engine, ike, pzu, "5", "50")

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")

        _save_trade(user, "Sprzedaż", "PZU", "8", "60")

        [error] = user.find(marker="transaction-error").elements
        assert isinstance(error, ui.label)
        assert error.text.startswith("Sprzedaż bez pokrycia") and "było 5 szt." in error.text
    assert len(list_transactions(engine)) == 1


async def test_covered_sell_is_saved(engine: Engine, ike: int, pzu: int) -> None:
    _buy(engine, ike, pzu, "5", "50")

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")

        _save_trade(user, "Sprzedaż", "PZU", "5", "60", fee="2")

        await user.open("/transakcje")
        with user.scope(marker="transactions"):
            await user.should_see(f"+298,00{NBSP}zł")


async def test_trade_needs_an_instrument(engine: Engine, ike: int, pzu: int) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")
        user.find(marker="add-transaction").click()
        user.find(marker="transaction-type").click()
        user.find("Zakup").click()
        user.find(marker="transaction-quantity").type("1")
        user.find(marker="transaction-price").type("1")
        user.find("Zapisz").click()

        await user.should_see("Wybierz instrument")
    assert list_transactions(engine) == []


async def test_dialog_offers_only_pln_instruments(engine: Engine, ike: int, pzu: int) -> None:
    add_instrument(engine, InstrumentDraft("Apple", list_asset_classes(engine)[2].id, "USD"))

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")
        user.find(marker="add-transaction").click()
        user.find(marker="transaction-type").click()
        user.find("Zakup").click()
        user.find(marker="transaction-instrument").click()

        await user.should_see("PZU")
        await user.should_not_see("Apple")


async def test_portfolio_card_shows_positions_valued_at_the_manual_price(engine: Engine, ike: int, pzu: int) -> None:
    _deposit(engine, ike, "1000")
    _buy(engine, ike, pzu, "10", "50", fee="5")

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/portfolio")

        with user.scope(marker="portfolio"):
            await user.should_see("PZU")
            await user.should_see(f"50,50{NBSP}zł")  # average price incl. commission
            await user.should_see(f"505,00{NBSP}zł")  # cost
            await user.should_see(f"60,00{NBSP}zł")  # Manual Price
            await user.should_see(f"600,00{NBSP}zł")  # value
            await user.should_see(f"+95,00{NBSP}zł")
            await user.should_see(f"+18,81{NBSP}%")
            await user.should_see(f"495,00{NBSP}zł")  # Cash Balance
            await user.should_see(f"1{NBSP}095,00{NBSP}zł")  # Account total: cash + positions


async def test_position_without_a_manual_price_is_shown_at_cost(engine: Engine, ike: int) -> None:
    cdr = _instrument(engine, "CD Projekt")
    _buy(engine, ike, cdr, "2", "100")

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/portfolio")

        with user.scope(marker="portfolio"):
            await user.should_see("CD Projekt")
            await user.should_see("brak ceny")
