"""The broker's FX Conversion Fee and the payment source in the transaction dialog (issue #17), without the network."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.transactions import BrokerConversion, TransactionType, buy_or_sell
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
USD_RATE = NbpRate("USD", Decimal("3.6045"), date(2026, 1, 5), "002/A/NBP/2026")
CHECKBOX = f"Prowizja XTB (przewalutowanie 0,50{NBSP}%)"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def xtb(engine: Engine) -> int:
    account = AccountDraft("XTB IKE", "XTB", AccountType.IKE, ("PLN",), fx_conversion_fee_percent=Decimal("0.5"))
    return add_account(engine, account).id


@pytest.fixture
def apple(engine: Engine) -> int:
    asset_class = list_asset_classes(engine)[2]
    return add_instrument(engine, InstrumentDraft("Apple", asset_class.id, "USD", manual_price=Decimal(160))).id


def _shell(engine: Engine) -> None:
    build_shell(engine, NbpRates(engine, fetch=lambda url: NBP_ANSWER, today=lambda: TODAY))


def _choose(user: User, marker: str, option: str) -> None:
    user.find(marker=marker).click()
    user.find(option).click()


def _start_buy(user: User, account: str = "XTB IKE", instrument: str = "Apple") -> None:
    user.find(marker="add-transaction").click()
    _choose(user, "transaction-type", "Zakup")
    _choose(user, "transaction-account", account)
    _choose(user, "transaction-instrument", instrument)
    user.find(marker="transaction-date").clear().type("07.01.2026")
    user.find(marker="transaction-quantity").type("10")
    user.find(marker="transaction-price").type("150,5")
    user.find(marker="transaction-commission").type("5")


async def test_fee_checkbox_shows_only_for_a_foreign_trade_on_an_account_with_a_fee(
    engine: Engine, xtb: int, apple: int
) -> None:
    add_account(engine, AccountDraft("mBank IKE", "mBank", AccountType.IKE, ("PLN",)))
    asset_class = list_asset_classes(engine)[1]
    add_instrument(engine, InstrumentDraft("Orlen", asset_class.id, "PLN"))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        _start_buy(user)
        await user.should_see(CHECKBOX)

        _choose(user, "transaction-account", "mBank IKE")
        await user.should_not_see(marker="transaction-conversion")

        _choose(user, "transaction-account", "XTB IKE")
        _choose(user, "transaction-instrument", "Orlen")
        await user.should_not_see(marker="transaction-conversion")


async def test_checked_fee_takes_the_charged_amount_and_records_the_fee(engine: Engine, xtb: int, apple: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        _start_buy(user)
        await user.should_not_see(marker="transaction-charged")
        user.find(marker="transaction-conversion").click()
        await user.should_not_see(marker="transaction-fx-rate")
        user.find(marker="transaction-charged").type("5 451,90")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see(f"-5{NBSP}456,90{NBSP}zł")
            await user.should_see(f"przewalutowanie 27,12{NBSP}zł")
    [buy] = list_transactions(engine)
    assert (buy.fx_conversion_fee, buy.fx_rate, buy.tax_amount) == (Decimal("27.12"), None, Decimal("5456.89"))


async def test_checked_fee_needs_the_charged_amount(engine: Engine, xtb: int, apple: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        _start_buy(user)
        user.find(marker="transaction-conversion").click()
        user.find("Zapisz").click()

        await user.should_see("Podaj kwotę pobraną przez brokera")
    assert list_transactions(engine) == []


async def test_unchecked_fee_converts_at_the_nbp_rate(engine: Engine, xtb: int, apple: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        _start_buy(user)
        user.find("Zapisz").click()
        await user.should_see(f"-5{NBSP}429,77{NBSP}zł")
    [buy] = list_transactions(engine)
    assert (buy.fx_conversion_fee, buy.actual_amount) == (None, Decimal("5429.77"))


async def test_editing_a_converted_trade_keeps_its_own_fee_after_the_account_drops_it(
    engine: Engine, xtb: int, apple: int
) -> None:
    conversion = BrokerConversion(Decimal("5451.90"), Decimal("0.5"))
    day = date(2026, 1, 7)
    buy = buy_or_sell(
        xtb,
        day,
        TransactionType.BUY,
        apple,
        Decimal(10),
        Decimal("150.5"),
        Decimal(5),
        nbp_rate=USD_RATE,
        conversion=conversion,
    )
    add_transaction(engine, buy)
    update_account(engine, xtb, AccountDraft("XTB IKE", "XTB", AccountType.IKE, ("PLN",)))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="transaction-row").click()
        await user.should_see(CHECKBOX)
        await user.should_see(marker="transaction-charged")
        user.find(marker="transaction-comment").type("bez zmian")
        user.find("Zapisz zmiany").click()
        await user.should_see("bez zmian")
    [edited] = list_transactions(engine)
    assert (edited.fx_conversion_fee, edited.actual_amount) == (Decimal("27.12"), Decimal("5456.90"))


async def test_account_holding_the_currency_lets_the_user_pay_in_pln(engine: Engine, apple: int) -> None:
    account = AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN", "USD"), fx_conversion_fee_percent=Decimal("0.5"))
    add_account(engine, account)

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        _start_buy(user, account="XTB")
        await user.should_see("gotówka USD")
        await user.should_not_see(marker="transaction-conversion")

        _choose(user, "transaction-paid-from", "PLN z przewalutowaniem")
        await user.should_not_see(marker="transaction-auto-exchange")
        user.find(marker="transaction-conversion").click()
        user.find(marker="transaction-charged").type("5451,90")
        user.find("Zapisz").click()
        await user.should_see(f"-5{NBSP}456,90{NBSP}zł")
    [buy] = list_transactions(engine)
    assert (buy.cash_currency, buy.fx_conversion_fee) == ("PLN", Decimal("27.12"))


async def test_editing_keeps_a_trade_paid_from_foreign_cash_after_the_account_drops_the_currency(
    engine: Engine, apple: int
) -> None:
    ibkr = add_account(engine, AccountDraft("IBKR", "IBKR", AccountType.REGULAR, ("PLN", "USD"))).id
    day = date(2026, 1, 7)
    paid_in_usd = buy_or_sell(
        ibkr, day, TransactionType.BUY, apple, Decimal(1), Decimal(100), nbp_rate=USD_RATE, cash_currency="USD"
    )
    add_transaction(engine, paid_in_usd)
    update_account(engine, ibkr, AccountDraft("IBKR", "IBKR", AccountType.REGULAR, ("PLN",)))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="transaction-row").click()
        await user.should_see("gotówka USD")
        user.find(marker="transaction-comment").type("bez zmian")
        user.find("Zapisz zmiany").click()
        await user.should_see("bez zmian")
    [edited] = list_transactions(engine)
    assert edited.cash_currency == "USD"
