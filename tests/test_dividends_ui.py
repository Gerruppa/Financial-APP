"""Dividends and interest, Costs and DRIP in the transaction dialog, Transakcje and Portfolio (issue #18)."""

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
from financial_app.domain.transactions import TransactionType, buy_or_sell, dividend
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
    return add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id


@pytest.fixture
def ibkr(engine: Engine) -> int:
    return add_account(engine, AccountDraft("IBKR", "IBKR", AccountType.REGULAR, ("PLN", "USD"))).id


@pytest.fixture
def pzu(engine: Engine) -> int:
    asset_class = list_asset_classes(engine)[1]
    return add_instrument(engine, InstrumentDraft("PZU", asset_class.id, "PLN", manual_price=Decimal(50))).id


@pytest.fixture
def apple(engine: Engine) -> int:
    asset_class = list_asset_classes(engine)[2]
    return add_instrument(engine, InstrumentDraft("Apple", asset_class.id, "USD", manual_price=Decimal(160))).id


def _shell(engine: Engine) -> None:
    build_shell(engine, NbpRates(engine, fetch=lambda url: NBP_ANSWER, today=lambda: TODAY))


def _choose(user: User, marker: str, option: str) -> None:
    user.find(marker=marker).click()
    user.find(option).click()


def _start(user: User, kind: str, account: str) -> None:
    user.find(marker="add-transaction").click()
    _choose(user, "transaction-type", kind)
    _choose(user, "transaction-account", account)
    user.find(marker="transaction-date").clear().type("07.01.2026")


async def test_pln_dividend_adds_its_net_amount_and_shows_gross_and_tax(engine: Engine, ike: int, pzu: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        _start(user, "Dywidenda / odsetki", "IKE")
        _choose(user, "transaction-instrument", "PZU")
        user.find(marker="transaction-gross").type("100")
        user.find(marker="transaction-withholding-tax").type("19")
        await user.should_see(f"Netto: 81,00{NBSP}zł")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see("Dywidenda / odsetki")
            await user.should_see(f"+81,00{NBSP}zł")
            await user.should_see(f"brutto 100,00{NBSP}zł · podatek 19,00{NBSP}zł")

        await user.open("/portfolio")
        with user.scope(marker="account-dividends"):
            await user.should_see(f"81,00{NBSP}zł")
    [saved] = list_transactions(engine)
    assert (saved.gross, saved.withholding_tax, saved.instrument_id) == (Decimal(100), Decimal(19), pzu)


async def test_interest_needs_no_instrument(engine: Engine, ike: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        _start(user, "Dywidenda / odsetki", "IKE")
        user.find(marker="transaction-gross").type("12,34")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see(f"+12,34{NBSP}zł")
    [saved] = list_transactions(engine)
    assert (saved.instrument_id, saved.actual_amount) == (None, Decimal("12.34"))


async def test_foreign_dividend_goes_into_the_accounts_usd_cash(engine: Engine, ibkr: int, apple: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        _start(user, "Dywidenda / odsetki", "IBKR")
        _choose(user, "transaction-instrument", "Apple")
        await user.should_see("gotówka USD")
        user.find(marker="transaction-gross").type("10")
        user.find(marker="transaction-withholding-tax").type("1,5")
        await user.should_see(f"Netto: 8,50{NBSP}USD")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see(f"+8,50{NBSP}USD")
            await user.should_see(f"brutto 10,00{NBSP}USD · podatek 1,50{NBSP}USD")

        await user.open("/portfolio")
        with user.scope(marker="foreign-cash"):
            await user.should_see(f"8,50{NBSP}USD")
    [saved] = list_transactions(engine)
    assert (saved.cash_currency, saved.nbp_rate) == ("USD", USD_RATE)


async def test_foreign_dividend_on_a_pln_account_is_converted_at_the_users_rate(
    engine: Engine, ike: int, apple: int
) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        _start(user, "Dywidenda / odsetki", "IKE")
        _choose(user, "transaction-instrument", "Apple")
        user.find(marker="transaction-gross").type("10")
        user.find(marker="transaction-fx-rate").type("3,5")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see(f"+35,00{NBSP}zł")
            await user.should_see(f"podatkowa +36,05{NBSP}zł")
    [saved] = list_transactions(engine)
    assert (saved.cash_currency, saved.fx_rate) == ("PLN", Decimal("3.5"))


async def test_tax_not_below_the_gross_amount_blocks_the_save(engine: Engine, ike: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        _start(user, "Dywidenda / odsetki", "IKE")
        user.find(marker="transaction-gross").type("10")
        user.find(marker="transaction-withholding-tax").type("10")
        user.find("Zapisz").click()

        await user.should_see("Podatek u źródła musi wynosić co najmniej 0 i mniej niż kwota brutto.")
    assert list_transactions(engine) == []


async def test_cost_takes_cash_and_shows_in_the_accounts_costs(engine: Engine, ike: int, pzu: int) -> None:
    add_transaction(
        engine, buy_or_sell(ike, date(2026, 1, 2), TransactionType.BUY, pzu, Decimal(1), Decimal(40), Decimal(3))
    )

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        _start(user, "Koszty", "IKE")
        await user.should_not_see(marker="transaction-instrument")
        user.find(marker="transaction-amount").type("10")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see("Koszty")
            await user.should_see(f"-10,00{NBSP}zł")

        await user.open("/portfolio")
        with user.scope(marker="account-costs"):
            await user.should_see(f"13,00{NBSP}zł")  # with the Buy's commission


async def test_drip_adds_a_lot_without_moving_cash(engine: Engine, ike: int, pzu: int) -> None:
    add_transaction(engine, buy_or_sell(ike, date(2026, 1, 2), TransactionType.BUY, pzu, Decimal(10), Decimal(40)))

    async with user_simulation(lambda: _shell(engine)) as user:
        # Not on Transakcje, whose list also names PZU
        await user.open("/")
        _start(user, "DRIP", "IKE")
        _choose(user, "transaction-instrument", "PZU")
        await user.should_not_see(marker="transaction-price")
        user.find(marker="transaction-quantity").type("0,5")
        user.find(marker="transaction-gross").type("25")
        user.find(marker="transaction-withholding-tax").type("4,75")
        user.find("Zapisz").click()

        await user.open("/transakcje")
        with user.scope(marker="transactions"):
            await user.should_see("DRIP")
            await user.should_see(f"reinwestowano 20,25{NBSP}zł")

        await user.open("/portfolio")
        user.find(marker="position-row").click()
        with user.scope(marker="position-lots"):
            await user.should_see("0,5")
            await user.should_see(f"20,25{NBSP}zł")
    drip_row = list_transactions(engine)[0]
    assert (drip_row.transaction_type, drip_row.quantity, drip_row.cash_change) == (
        TransactionType.DRIP,
        Decimal("0.5"),
        Decimal(0),
    )


async def test_editing_a_dividend_keeps_its_gross_and_tax(engine: Engine, ibkr: int, apple: int) -> None:
    payout = dividend(
        ibkr, date(2026, 1, 7), Decimal("10.25"), Decimal("1.5"), instrument_id=apple, nbp_rate=USD_RATE,
        cash_currency="USD",
    )  # fmt: skip
    add_transaction(engine, payout)

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="transaction-row").click()
        await user.should_see(f"Netto: 8,75{NBSP}USD")
        user.find(marker="transaction-comment").type("Q4")
        user.find("Zapisz zmiany").click()
        await user.should_see("Q4")
    [edited] = list_transactions(engine)
    assert (edited.gross, edited.withholding_tax, edited.cash_currency, edited.comment) == (
        Decimal("10.25"),
        Decimal("1.5"),
        "USD",
        "Q4",
    )


async def test_interest_in_a_foreign_cash_currency_goes_into_that_cash(engine: Engine, ibkr: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        _start(user, "Dywidenda / odsetki", "IBKR")
        _choose(user, "transaction-dividend-currency", "USD")
        user.find(marker="transaction-gross").type("2")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see(f"+2,00{NBSP}USD")
    [saved] = list_transactions(engine)
    assert (saved.instrument_id, saved.cash_currency, saved.nbp_rate) == (None, "USD", USD_RATE)
