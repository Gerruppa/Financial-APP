"""Foreign-currency Buys and Sells with the NBP Rate (D-1) end to end (issue #15), without the network."""

import json
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
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
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


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def ike(engine: Engine) -> int:
    return add_account(engine, AccountDraft("mBank IKE", "mBank", AccountType.IKE, ("PLN",))).id


@pytest.fixture
def apple(engine: Engine) -> int:
    asset_class = list_asset_classes(engine)[2]
    return add_instrument(engine, InstrumentDraft("Apple", asset_class.id, "USD", manual_price=Decimal(160))).id


def _shell(engine: Engine, nbp_answer: str | None = NBP_ANSWER) -> None:
    build_shell(engine, NbpRates(engine, fetch=lambda url: nbp_answer, today=lambda: TODAY))


def _save_foreign_buy(user: User, fx_rate: str = "") -> None:
    user.find(marker="add-transaction").click()
    user.find(marker="transaction-type").click()
    user.find("Zakup").click()
    user.find(marker="transaction-instrument").click()
    user.find("Apple").click()
    user.find(marker="transaction-date").clear().type("07.01.2026")
    user.find(marker="transaction-quantity").type("10")
    user.find(marker="transaction-price").type("150,5")
    user.find(marker="transaction-commission").type("5")
    if fx_rate:
        user.find(marker="transaction-fx-rate").type(fx_rate)
    user.find("Zapisz").click()


async def test_foreign_buy_without_a_rate_of_its_own_uses_the_nbp_rate(engine: Engine, ike: int, apple: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")

        _save_foreign_buy(user)

        with user.scope(marker="transactions"):
            await user.should_see(f"10 × 150,50{NBSP}USD")
            await user.should_see(f"-5{NBSP}429,77{NBSP}zł")
            await user.should_see("NBP 3,6045 (002/A/NBP/2026 z 05.01.2026)")
    [buy] = list_transactions(engine)
    assert (buy.fx_rate, buy.nbp_rate, buy.tax_amount) == (None, USD_RATE, Decimal("5429.77"))


async def test_foreign_buy_at_the_users_rate_shows_both_amounts(engine: Engine, ike: int, apple: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")

        _save_foreign_buy(user, fx_rate="3,65")

        with user.scope(marker="transactions"):
            await user.should_see(f"-5{NBSP}498,25{NBSP}zł")
            await user.should_see(f"podatkowa -5{NBSP}429,77{NBSP}zł")
            await user.should_see("kurs 3,65")


async def test_missing_nbp_rate_blocks_saving_with_a_message(engine: Engine, ike: int, apple: int) -> None:
    async with user_simulation(lambda: _shell(engine, nbp_answer=None)) as user:
        await user.open("/")

        _save_foreign_buy(user, fx_rate="3,65")

        [error] = user.find(marker="transaction-error").elements
        assert isinstance(error, ui.label)
        assert error.text.startswith("Brak kursu NBP USD sprzed 07.01.2026")
    assert list_transactions(engine) == []


async def test_rate_field_shows_only_for_a_foreign_currency_instrument(engine: Engine, ike: int, apple: int) -> None:
    asset_class = list_asset_classes(engine)[1]
    add_instrument(engine, InstrumentDraft("PZU", asset_class.id, "PLN"))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")
        user.find(marker="add-transaction").click()
        user.find(marker="transaction-type").click()
        user.find("Zakup").click()
        user.find(marker="transaction-instrument").click()
        user.find("PZU").click()
        await user.should_not_see(marker="transaction-fx-rate")

        user.find(marker="transaction-instrument").click()
        user.find("Apple").click()
        await user.should_see(marker="transaction-fx-rate")
        await user.should_see("Cena (USD)")


async def test_editing_a_foreign_buy_keeps_the_users_rate(engine: Engine, ike: int, apple: int) -> None:
    add_transaction(engine, _apple_buy(ike, apple))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="transaction-row").click()

        [fx_rate] = user.find(marker="transaction-fx-rate").elements
        assert isinstance(fx_rate, ui.input)
        assert fx_rate.value == "3,65"


def _apple_buy(account_id: int, instrument_id: int) -> TransactionDraft:
    return buy_or_sell(
        account_id,
        date(2026, 1, 7),
        TransactionType.BUY,
        instrument_id,
        Decimal(10),
        Decimal("150.5"),
        Decimal(5),
        fx_rate=Decimal("3.65"),
        nbp_rate=USD_RATE,
    )


async def test_position_details_show_each_lots_actual_and_tax_cost(engine: Engine, ike: int, apple: int) -> None:
    add_transaction(engine, _apple_buy(ike, apple))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/portfolio")
        await user.should_not_see("Koszt podatkowy")

        user.find(marker="position-row").click()

        with user.scope(marker="position-lots"):
            await user.should_see("07.01.2026")
            await user.should_see(f"5{NBSP}498,25{NBSP}zł")  # Actual cost
            await user.should_see(f"5{NBSP}429,77{NBSP}zł")  # Tax cost


async def test_foreign_position_is_valued_at_the_manual_price_and_the_nbp_rate(
    engine: Engine, ike: int, apple: int
) -> None:
    add_transaction(engine, _apple_buy(ike, apple))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/portfolio")

        with user.scope(marker="portfolio"):
            await user.should_see(f"160,00{NBSP}USD")
            await user.should_see(f"5{NBSP}767,20{NBSP}zł")  # 10 × 160 USD × 3,6045


async def test_foreign_position_without_a_rate_counts_at_cost(engine: Engine, ike: int, apple: int) -> None:
    add_transaction(engine, _apple_buy(ike, apple))

    async with user_simulation(lambda: _shell(engine, nbp_answer=None)) as user:
        await user.open("/portfolio")

        with user.scope(marker="portfolio"):
            await user.should_see("brak kursu")


async def test_editing_a_foreign_trade_offline_keeps_its_nbp_rate(engine: Engine, ike: int, apple: int) -> None:
    add_transaction(engine, _apple_buy(ike, apple))

    async with user_simulation(lambda: _shell(engine, nbp_answer=None)) as user:
        await user.open("/transakcje")
        user.find(marker="transaction-row").click()
        user.find(marker="transaction-comment").type("Apple na IKE")
        user.find("Zapisz zmiany").click()

        with user.scope(marker="transactions"):
            await user.should_see("Apple na IKE")
    [buy] = list_transactions(engine)
    assert buy.nbp_rate == USD_RATE


def test_tax_cash_change_has_the_sign_of_the_cash_change() -> None:
    buy = _apple_buy(1, 2)

    assert buy.tax_cash_change == -buy.tax_amount
