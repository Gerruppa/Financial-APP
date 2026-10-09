"""Saving Currency Exchanges and Buys paid from foreign cash in SQLite (issue #16)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.transactions import (
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
    covering_exchange,
    currency_exchange,
)
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import add_transaction, add_transactions, list_transactions

USD_RATE = NbpRate("USD", Decimal("3.6045"), date(2026, 1, 5), "002/A/NBP/2026")


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def usd_account(engine: Engine) -> int:
    return add_account(engine, AccountDraft("IBKR", "IBKR", AccountType.REGULAR, ("PLN", "USD"))).id


@pytest.fixture
def pln_account(engine: Engine) -> int:
    return add_account(engine, AccountDraft("mBank", "mBank", AccountType.REGULAR, ("PLN",))).id


@pytest.fixture
def apple(engine: Engine) -> int:
    asset_class = list_asset_classes(engine)[2]
    return add_instrument(engine, InstrumentDraft("Apple", asset_class.id, "USD")).id


def _usd_buy(account_id: int, instrument_id: int) -> TransactionDraft:
    return buy_or_sell(
        account_id,
        date(2026, 1, 7),
        TransactionType.BUY,
        instrument_id,
        Decimal(10),
        Decimal("150.5"),
        Decimal(5),
        nbp_rate=USD_RATE,
        cash_currency="USD",
    )


def test_exchange_is_listed_with_its_currency_and_direction(engine: Engine, usd_account: int) -> None:
    saved = add_transaction(
        engine, currency_exchange(usd_account, date(2026, 1, 7), "USD", Decimal(500), Decimal("1850.25"), to_pln=True)
    )

    [listed] = list_transactions(engine)
    assert listed == saved
    assert (listed.cash_currency, listed.quantity, listed.actual_amount, listed.to_pln) == (
        "USD",
        Decimal(500),
        Decimal("1850.25"),
        True,
    )


def test_buy_paid_from_usd_cash_keeps_its_cash_currency(engine: Engine, usd_account: int, apple: int) -> None:
    add_transaction(engine, _usd_buy(usd_account, apple))

    [listed] = list_transactions(engine)
    assert listed.cash_currency == "USD"
    assert listed.foreign_cash_change == Decimal("-1505.00")


def test_foreign_cash_needs_an_account_holding_that_currency(engine: Engine, pln_account: int, apple: int) -> None:
    with pytest.raises(TransactionError, match="mBank nie ma waluty rachunku USD"):
        add_transaction(engine, currency_exchange(pln_account, date(2026, 1, 7), "USD", Decimal(1), Decimal(4)))
    with pytest.raises(TransactionError, match="mBank nie ma waluty rachunku USD"):
        add_transaction(engine, _usd_buy(pln_account, apple))
    assert list_transactions(engine) == []


def test_automatic_exchange_and_buy_are_saved_together_in_that_order(
    engine: Engine, usd_account: int, apple: int
) -> None:
    buy = _usd_buy(usd_account, apple)
    exchange = covering_exchange(buy)

    saved = add_transactions(engine, [exchange, buy])

    assert [t.transaction_type for t in saved] == [TransactionType.CURRENCY_EXCHANGE, TransactionType.BUY]
    assert [t.id for t in reversed(list_transactions(engine))] == [t.id for t in saved]


def test_nothing_is_saved_when_one_of_several_is_rejected(engine: Engine, usd_account: int, apple: int) -> None:
    exchange = currency_exchange(usd_account, date(2026, 1, 7), "USD", Decimal(1), Decimal(4))
    sell = buy_or_sell(
        usd_account, date(2026, 1, 7), TransactionType.SELL, apple, Decimal(1), Decimal(1), nbp_rate=USD_RATE
    )

    with pytest.raises(TransactionError):
        add_transactions(engine, [exchange, sell])

    assert list_transactions(engine) == []
