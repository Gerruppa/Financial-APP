"""Saving Dividends, Costs and DRIPs in SQLite (issue #18)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.lots import InsufficientQuantityError, open_positions
from financial_app.domain.transactions import (
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
    cost,
    dividend,
    drip,
)
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import (
    add_transaction,
    delete_transaction,
    list_transactions,
    update_transaction,
)

USD_RATE = NbpRate("USD", Decimal("3.6045"), date(2026, 1, 5), "002/A/NBP/2026")
DAY = date(2026, 1, 7)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def ibkr(engine: Engine) -> int:
    return add_account(engine, AccountDraft("IBKR", "IBKR", AccountType.REGULAR, ("PLN", "USD"))).id


@pytest.fixture
def ike(engine: Engine) -> int:
    return add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id


@pytest.fixture
def apple(engine: Engine) -> int:
    asset_class = list_asset_classes(engine)[2]
    return add_instrument(engine, InstrumentDraft("Apple", asset_class.id, "USD")).id


@pytest.fixture
def pzu(engine: Engine) -> int:
    asset_class = list_asset_classes(engine)[1]
    return add_instrument(engine, InstrumentDraft("PZU", asset_class.id, "PLN")).id


def test_foreign_dividend_into_foreign_cash_keeps_gross_tax_and_currency(engine: Engine, ibkr: int, apple: int) -> None:
    draft = dividend(
        ibkr, DAY, Decimal(10), Decimal("1.50"), "Q4", instrument_id=apple, nbp_rate=USD_RATE, cash_currency="USD"
    )

    saved = add_transaction(engine, draft)

    [listed] = list_transactions(engine)
    assert listed == saved
    assert (listed.gross, listed.withholding_tax, listed.net) == (Decimal(10), Decimal("1.50"), Decimal("8.50"))
    assert listed.cash_currency == "USD"
    assert listed.actual_amount == Decimal("30.64")


def test_interest_and_cost_are_saved_without_an_instrument(engine: Engine, ike: int) -> None:
    add_transaction(engine, dividend(ike, DAY, Decimal("12.34")))
    add_transaction(engine, TransactionDraft(ike, DAY, TransactionType.COST, Decimal(5), "Opłata za konto"))

    cost, interest = list_transactions(engine)
    assert (interest.transaction_type, interest.gross, interest.withholding_tax) == (
        TransactionType.DIVIDEND,
        Decimal("12.34"),
        Decimal(0),
    )
    assert (cost.transaction_type, cost.actual_amount, cost.comment) == (
        TransactionType.COST,
        Decimal(5),
        "Opłata za konto",
    )


def test_foreign_dividend_needs_the_nbp_rate_of_its_instrument(engine: Engine, ike: int, apple: int) -> None:
    with pytest.raises(TransactionError, match="Brak kursu NBP"):
        add_transaction(engine, dividend(ike, DAY, Decimal(10), instrument_id=apple))


def test_foreign_cash_dividend_needs_an_account_holding_the_currency(engine: Engine, ike: int, apple: int) -> None:
    draft = dividend(ike, DAY, Decimal(10), instrument_id=apple, nbp_rate=USD_RATE, cash_currency="USD")

    with pytest.raises(TransactionError, match="USD"):
        add_transaction(engine, draft)


def test_foreign_interest_needs_an_nbp_rate_from_before_its_day(engine: Engine, ibkr: int) -> None:
    late = NbpRate("USD", Decimal("3.6"), DAY, "003/A/NBP/2026")

    with pytest.raises(TransactionError, match="dnia roboczego"):
        add_transaction(engine, dividend(ibkr, DAY, Decimal(1), nbp_rate=late, cash_currency="USD"))


def test_drip_lot_covers_a_later_sell_and_cannot_then_be_deleted(engine: Engine, ike: int, pzu: int) -> None:
    add_transaction(engine, buy_or_sell(ike, date(2026, 1, 2), TransactionType.BUY, pzu, Decimal(10), Decimal(40)))
    reinvested = add_transaction(engine, drip(ike, DAY, pzu, Decimal("0.5"), Decimal(25), Decimal("4.75")))
    add_transaction(engine, buy_or_sell(ike, date(2026, 1, 9), TransactionType.SELL, pzu, Decimal("10.5"), Decimal(45)))

    assert list_transactions(engine)[1] == reinvested
    assert open_positions(reversed(list_transactions(engine))) == []
    with pytest.raises(InsufficientQuantityError):
        delete_transaction(engine, reinvested.id)
    with pytest.raises(InsufficientQuantityError):
        update_transaction(engine, reinvested.id, drip(ike, DAY, pzu, Decimal("0.4"), Decimal(25)))


def test_foreign_cost_needs_an_account_holding_the_currency(engine: Engine, ike: int, ibkr: int) -> None:
    add_transaction(engine, cost(ibkr, DAY, Decimal(10), cash_currency="USD", nbp_rate=USD_RATE))

    with pytest.raises(TransactionError, match="USD"):
        add_transaction(engine, cost(ike, DAY, Decimal(10), cash_currency="USD", nbp_rate=USD_RATE))
    [saved] = list_transactions(engine)
    assert (saved.quantity, saved.cash_currency, saved.nbp_rate) == (Decimal(10), "USD", USD_RATE)
