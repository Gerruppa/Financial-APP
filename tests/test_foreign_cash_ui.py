"""Foreign cash, Currency Exchange and the FX result end to end (issue #16), without the network."""

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.transactions import TransactionType, buy_or_sell, currency_exchange
from financial_app.persistence.accounts import add_account, update_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import add_transaction, list_transactions
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell

NBSP = "\xa0"
TODAY = date(2026, 1, 8)
# Whatever window is asked for, the NBP answers with Monday 5 January 2026
NBP_ANSWER = json.dumps(
    {"table": "A", "code": "USD", "rates": [{"no": "002/A/NBP/2026", "effectiveDate": "2026-01-05", "mid": 3.6045}]}
)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def ibkr(engine: Engine) -> int:
    return add_account(engine, AccountDraft("IBKR", "IBKR", AccountType.REGULAR, ("PLN", "USD"))).id


@pytest.fixture
def apple(engine: Engine) -> int:
    asset_class = list_asset_classes(engine)[2]
    return add_instrument(engine, InstrumentDraft("Apple", asset_class.id, "USD", manual_price=Decimal(160))).id


def _shell(engine: Engine) -> None:
    build_shell(engine, NbpRates(engine, fetch=lambda url: NBP_ANSWER, today=lambda: TODAY))


def _choose(user: User, marker: str, option: str) -> None:
    user.find(marker=marker).click()
    user.find(option).click()


def _start_buy(user: User, account: str = "IBKR") -> None:
    user.find(marker="add-transaction").click()
    _choose(user, "transaction-type", "Zakup")
    _choose(user, "transaction-account", account)
    _choose(user, "transaction-instrument", "Apple")
    user.find(marker="transaction-date").clear().type("07.01.2026")
    user.find(marker="transaction-quantity").type("10")
    user.find(marker="transaction-price").type("150,5")
    user.find(marker="transaction-commission").type("5")


async def test_exchange_from_pln_is_listed_and_held_as_usd_cash(engine: Engine, ibkr: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="add-transaction").click()
        _choose(user, "transaction-type", "Wymiana walut")
        user.find(marker="transaction-date").clear().type("07.01.2026")
        user.find(marker="transaction-foreign-amount").type("1 000")
        user.find(marker="transaction-amount").type("3 650")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see("Wymiana walut")
            await user.should_see("PLN → USD")
            await user.should_see(f"+1{NBSP}000,00{NBSP}USD po 3,6500{NBSP}zł")
            await user.should_see(f"-3{NBSP}650,00{NBSP}zł")

        await user.open("/portfolio")
        with user.scope(marker="foreign-cash"):
            await user.should_see(f"1{NBSP}000,00{NBSP}USD")
            await user.should_see(f"3{NBSP}604,50{NBSP}zł")  # at the NBP Rate 3,6045
            await user.should_see(f"-45,50{NBSP}zł")
    [exchange] = list_transactions(engine)
    assert (exchange.cash_currency, exchange.quantity, exchange.to_pln) == ("USD", Decimal(1000), False)


async def test_exchange_to_pln_sells_the_currency(engine: Engine, ibkr: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="add-transaction").click()
        _choose(user, "transaction-type", "Wymiana walut")
        _choose(user, "transaction-direction", "USD → PLN")
        user.find(marker="transaction-foreign-amount").type("100")
        user.find(marker="transaction-amount").type("370")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see(f"+370,00{NBSP}zł")
    [exchange] = list_transactions(engine)
    assert exchange.to_pln


async def test_buy_on_an_account_holding_usd_is_paid_from_usd_cash(engine: Engine, ibkr: int, apple: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        _start_buy(user)
        await user.should_see("gotówka USD")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see(f"-1{NBSP}505,00{NBSP}USD")
    [buy] = list_transactions(engine)
    assert buy.cash_currency == "USD"
    assert buy.cash_change == Decimal(-5)


async def test_automatic_exchange_buys_exactly_the_dollars_of_the_buy(engine: Engine, ibkr: int, apple: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        _start_buy(user)
        user.find(marker="transaction-auto-exchange").click()
        user.find("Zapisz").click()
        await user.should_see("Wymiana walut")

    buy, exchange = list_transactions(engine)
    assert exchange.transaction_type is TransactionType.CURRENCY_EXCHANGE
    # 1505 USD at the NBP Rate 3,6045; the 5 zł commission stays in PLN
    assert (exchange.quantity, exchange.actual_amount) == (Decimal("1505.00"), Decimal("5424.77"))
    assert buy.actual_amount == Decimal("5429.77")


async def test_automatic_exchange_is_offered_only_for_a_buy_paid_in_foreign_cash(
    engine: Engine, ibkr: int, apple: int
) -> None:
    add_account(engine, AccountDraft("mBank IKE", "mBank", AccountType.IKE, ("PLN",)))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")
        _start_buy(user, account="mBank IKE")
        await user.should_not_see(marker="transaction-auto-exchange")
        await user.should_not_see("gotówka USD")

        _choose(user, "transaction-account", "IBKR")
        await user.should_see(marker="transaction-auto-exchange")

        _choose(user, "transaction-type", "Sprzedaż")
        await user.should_not_see(marker="transaction-auto-exchange")


async def test_fx_result_counts_in_the_account_result_unless_the_account_excludes_it(engine: Engine) -> None:
    excluded = AccountDraft("Kantor", "Kantor", AccountType.REGULAR, ("PLN", "USD"), exclude_fx_result=True)
    for account in (AccountDraft("IBKR", "IBKR", AccountType.REGULAR, ("PLN", "USD")), excluded):
        account_id = add_account(engine, account).id
        add_transaction(engine, currency_exchange(account_id, date(2026, 1, 7), "USD", Decimal(1000), Decimal(3500)))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/portfolio")

        results = _texts(user, "account-result")
        fx_results = _texts(user, "fx-result")
    # 1000 USD bought at 3,50 zł, worth 3,6045 zł now
    assert sorted(results) == [f"+0,00{NBSP}zł", f"+104,50{NBSP}zł"]
    assert sorted(fx_results) == [f"+104,50{NBSP}zł", f"+104,50{NBSP}zł (wyłączony z wyniku konta)"]


def _texts(user: User, marker: str) -> list[str]:
    """The texts of the labels with ``marker``; elements come unordered, so callers sort them."""
    return [element.text for element in user.find(marker=marker).elements if isinstance(element, ui.label)]


async def test_editing_an_exchange_keeps_its_direction_and_currency(engine: Engine, ibkr: int) -> None:
    sale = currency_exchange(ibkr, date(2026, 1, 7), "USD", Decimal("100.5"), Decimal(370), to_pln=True)
    add_transaction(engine, sale)

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="transaction-row").click()
        await user.should_see("USD → PLN")
        user.find(marker="transaction-amount").clear().type("380")
        user.find("Zapisz zmiany").click()

        with user.scope(marker="transactions"):
            await user.should_see(f"+380,00{NBSP}zł")
    [edited] = list_transactions(engine)
    assert (edited.cash_currency, edited.quantity, edited.actual_amount, edited.to_pln) == (
        "USD",
        Decimal("100.5"),
        Decimal(380),
        True,
    )


async def test_editing_keeps_how_a_trade_was_paid_after_the_account_gains_a_currency(
    engine: Engine, apple: int
) -> None:
    account = AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))
    xtb = add_account(engine, account).id
    rate = NbpRate("USD", Decimal("3.6045"), date(2026, 1, 5), "002/A/NBP/2026")
    pln_paid = buy_or_sell(xtb, date(2026, 1, 7), TransactionType.BUY, apple, Decimal(1), Decimal(100), nbp_rate=rate)
    add_transaction(engine, pln_paid)
    update_account(engine, xtb, replace(account, cash_currencies=("PLN", "USD")))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="transaction-row").click()
        await user.should_not_see("gotówka USD")
        user.find(marker="transaction-comment").type("bez zmian")
        user.find("Zapisz zmiany").click()
        await user.should_see("bez zmian")
    [edited] = list_transactions(engine)
    assert edited.cash_currency == "PLN"
