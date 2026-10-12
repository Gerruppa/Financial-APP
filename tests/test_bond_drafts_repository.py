"""Confirming maturity, Rollover and coupon Drafts (L-6, L-8, spec 3.4.1): a redemption saves the Lot's Sell, a Rollover
also the Buy of the new Series, all or nothing; a coupon an interest Dividend naming the Lot."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.bond_drafts import CouponDraft, MaturityDraft
from financial_app.domain.bonds import BondType, SeriesTerms
from financial_app.domain.transactions import TransactionDraft, TransactionError, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.bond_data import save_series_terms
from financial_app.persistence.bond_drafts import confirm_draft, confirm_rollover, pending_drafts, rollover_price
from financial_app.persistence.bond_series import series_instrument
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import add_transaction, delete_transaction, list_transactions

TODAY = date(2026, 10, 8)


def _terms(name: str, sold: date, rollover: str) -> SeriesTerms:
    return SeriesTerms(
        name, "PL0000119145", sold, sold, Decimal(100), Decimal(rollover), Decimal("0.01"), (Decimal("0.03"),) * 10, ()
    )


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = init_db(tmp_path / "app.sqlite3")
    save_series_terms(
        engine, [_terms("EDO0626", date(2016, 6, 1), "99.9"), _terms("EDO0636", date(2026, 6, 1), "99.8")]
    )
    return engine


def _bought(engine: Engine, quantity: int = 10) -> int:
    account = add_account(engine, AccountDraft("Obligacje", "PKO BP", AccountType.BONDS, ("PLN",)))
    instrument, _ = series_instrument(engine, "EDO0626")
    day = date(2016, 6, 15)
    add_transaction(engine, TransactionDraft(account.id, day, TransactionType.DEPOSIT, Decimal(quantity * 100)))
    add_transaction(
        engine, buy_or_sell(account.id, day, TransactionType.BUY, instrument.id, Decimal(quantity), Decimal(100))
    )
    return account.id


def test_a_confirmed_redemption_sells_the_lot_and_the_draft_goes(engine: Engine) -> None:
    _bought(engine)
    [draft] = pending_drafts(engine, TODAY)

    confirm_draft(engine, draft)

    sell = list_transactions(engine)[0]
    assert sell.transaction_type is TransactionType.SELL
    assert sell.actual_amount == Decimal("1278.60")
    assert pending_drafts(engine, TODAY) == []


def _maturity(engine: Engine) -> MaturityDraft:
    [draft] = pending_drafts(engine, TODAY)
    assert isinstance(draft, MaturityDraft)
    return draft


def test_a_rollover_redeems_the_lot_and_buys_the_new_series_at_its_rollover_price(engine: Engine) -> None:
    _bought(engine)
    draft = _maturity(engine)

    assert rollover_price(engine, "EDO0636") == Decimal("99.8")
    confirm_rollover(engine, draft, BondType.EDO, Decimal(10))

    buy, sell = list_transactions(engine)[:2]
    assert sell.transaction_type is TransactionType.SELL
    assert buy.transaction_type is TransactionType.BUY
    assert buy.date == date(2026, 6, 15)
    assert buy.actual_amount == Decimal("998.0")
    assert {i.name for i in list_instruments(engine)} == {"EDO0626", "EDO0636"}
    assert pending_drafts(engine, TODAY) == []


def test_a_series_missing_from_the_mf_file_rolls_at_the_default_price(engine: Engine) -> None:
    assert rollover_price(engine, "COI0630") == Decimal("99.90")


def test_a_failed_rollover_saves_nothing_and_drops_the_series_it_created(engine: Engine) -> None:
    _bought(engine)
    draft = _maturity(engine)

    with pytest.raises(TransactionError):
        confirm_rollover(engine, draft, BondType.COI, Decimal(0))

    assert len(list_transactions(engine)) == 2
    assert [i.name for i in list_instruments(engine)] == ["EDO0626"]


def _coi(engine: Engine) -> None:
    rates = (Decimal("0.0655"), Decimal("0.0615"), None, None)
    terms = SeriesTerms(
        "COI0528", "PL0000119145", date(2024, 5, 1), date(2024, 5, 31), Decimal(100), Decimal("99.9"),
        Decimal("0.0125"), rates, (),
    )  # fmt: skip
    save_series_terms(engine, [terms])
    account = add_account(engine, AccountDraft("Obligacje", "PKO BP", AccountType.BONDS, ("PLN",)))
    instrument, _ = series_instrument(engine, "COI0528")
    day = date(2024, 5, 20)
    add_transaction(engine, TransactionDraft(account.id, day, TransactionType.DEPOSIT, Decimal(1000)))
    add_transaction(engine, buy_or_sell(account.id, day, TransactionType.BUY, instrument.id, Decimal(10), Decimal(100)))


def test_a_confirmed_coupon_saves_interest_naming_the_lot_and_its_draft_goes(engine: Engine) -> None:
    _coi(engine)
    first, second = pending_drafts(engine, TODAY)
    assert isinstance(first, CouponDraft) and isinstance(second, CouponDraft)

    confirm_draft(engine, first)

    interest = list_transactions(engine)[0]
    buy = list_transactions(engine)[1]
    assert interest.transaction_type is TransactionType.DIVIDEND
    assert (interest.date, interest.instrument_id, interest.lot_id) == (date(2025, 5, 20), None, buy.id)
    assert (interest.gross, interest.withholding_tax, interest.actual_amount) == (
        Decimal("65.50"),
        Decimal("12.40"),
        Decimal("53.10"),
    )
    assert pending_drafts(engine, TODAY) == [second]


def test_a_buy_whose_coupon_was_entered_cannot_be_deleted(engine: Engine) -> None:
    _coi(engine)
    confirm_draft(engine, pending_drafts(engine, TODAY)[0])
    buy = list_transactions(engine)[1]

    with pytest.raises(TransactionError, match="odsetki"):
        delete_transaction(engine, buy.id)
