"""Saving a Cash Transfer in a foreign currency (issue #125): both Accounts must hold the currency."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.transactions import TransactionDraft, TransactionError, cash_transfer
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.reconciliation import incoming_transfers, unreconciled_transactions
from financial_app.persistence.transactions import add_transaction, list_transactions

RATE = NbpRate("USD", Decimal("4.00"), date(2026, 1, 9), "006/A/NBP/2026")


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _account(engine: Engine, name: str, *currencies: str) -> int:
    return add_account(engine, AccountDraft(name, "IBKR", AccountType.REGULAR, currencies)).id


def _usd_transfer(source: int, target: int) -> TransactionDraft:
    return cash_transfer(source, date(2026, 1, 10), target, Decimal(100), cash_currency="USD", nbp_rate=RATE)


def test_usd_transfer_is_listed_with_its_currency_and_rate(engine: Engine) -> None:
    source, target = _account(engine, "IBKR", "PLN", "USD"), _account(engine, "Revolut", "USD")

    saved = add_transaction(engine, _usd_transfer(source, target))

    [listed] = list_transactions(engine)
    assert listed == saved
    assert (listed.cash_currency, listed.quantity, listed.actual_amount) == ("USD", Decimal(100), Decimal("400.00"))


def test_reconciliation_leaves_usd_transfers_alone(engine: Engine) -> None:
    xtb, ibkr = _account(engine, "XTB", "PLN", "USD"), _account(engine, "IBKR", "PLN", "USD")
    add_transaction(engine, _usd_transfer(xtb, ibkr))
    add_transaction(engine, _usd_transfer(ibkr, xtb))
    days = (date(2026, 1, 1), date(2026, 1, 31))

    # The XTB statement shows PLN only (spec 7), so neither leg is the broker's to pair or to take away
    assert unreconciled_transactions(engine, {xtb: days}) == []
    assert incoming_transfers(engine, {xtb: days}) == []


def test_usd_transfer_needs_both_accounts_to_hold_usd(engine: Engine) -> None:
    usd, pln_only = _account(engine, "IBKR", "PLN", "USD"), _account(engine, "mBank", "PLN")

    with pytest.raises(TransactionError, match="mBank nie ma waluty rachunku USD"):
        add_transaction(engine, _usd_transfer(usd, pln_only))
    assert list_transactions(engine) == []
