"""Saving a trade with its commission in foreign cash on an Account without PLN (issue #124)."""

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
    cash_transfer,
)
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import add_transaction, list_transactions

RATE = NbpRate("USD", Decimal("4.00"), date(2026, 1, 2), "001/A/NBP/2026")


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def revolut(engine: Engine) -> int:
    return add_account(engine, AccountDraft("Revolut", "Revolut", AccountType.REGULAR, ("USD",))).id


@pytest.fixture
def apple(engine: Engine) -> int:
    return add_instrument(engine, InstrumentDraft("Apple", list_asset_classes(engine)[2].id, "USD")).id


def test_usd_commission_is_listed_in_usd(engine: Engine, revolut: int, apple: int) -> None:
    buy = buy_or_sell(
        revolut,
        date(2026, 1, 5),
        TransactionType.BUY,
        apple,
        Decimal(10),
        Decimal(100),
        Decimal("2.50"),
        nbp_rate=RATE,
        cash_currency="USD",
        commission_currency="USD",
    )

    saved = add_transaction(engine, buy)

    [listed] = list_transactions(engine)
    assert listed == saved
    assert listed.commission_currency == "USD"
    assert listed.foreign_cash_change == Decimal("-1002.50")


def test_nothing_moving_pln_is_saved_on_an_account_without_pln(engine: Engine, revolut: int, apple: int) -> None:
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    pln_commission = buy_or_sell(
        revolut, date(2026, 1, 5), TransactionType.BUY, apple, Decimal(1), Decimal(100), Decimal(5),
        nbp_rate=RATE, cash_currency="USD",
    )  # fmt: skip
    refused = [
        TransactionDraft(revolut, date(2026, 1, 5), TransactionType.DEPOSIT, Decimal(100)),
        pln_commission,
        cash_transfer(ike, date(2026, 1, 5), revolut, Decimal(100)),
    ]

    for draft in refused:
        with pytest.raises(TransactionError, match="Revolut nie ma waluty rachunku PLN"):
            add_transaction(engine, draft)
    assert list_transactions(engine) == []
