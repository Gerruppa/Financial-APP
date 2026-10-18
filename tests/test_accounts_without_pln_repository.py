"""Saving a trade with its commission in foreign cash on an Account without PLN (issue #124)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.transactions import TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import add_transaction, list_transactions


def test_usd_commission_is_listed_in_usd(tmp_path: Path) -> None:
    engine = init_db(tmp_path / "app.sqlite3")
    account = add_account(engine, AccountDraft("Revolut", "Revolut", AccountType.REGULAR, ("USD",))).id
    apple = add_instrument(engine, InstrumentDraft("Apple", list_asset_classes(engine)[2].id, "USD")).id
    rate = NbpRate("USD", Decimal("4.00"), date(2026, 1, 2), "001/A/NBP/2026")
    buy = buy_or_sell(
        account,
        date(2026, 1, 5),
        TransactionType.BUY,
        apple,
        Decimal(10),
        Decimal(100),
        Decimal("2.50"),
        nbp_rate=rate,
        cash_currency="USD",
        commission_currency="USD",
    )

    saved = add_transaction(engine, buy)

    [listed] = list_transactions(engine)
    assert listed == saved
    assert listed.commission_currency == "USD"
    assert listed.foreign_cash_change == Decimal("-1002.50")
