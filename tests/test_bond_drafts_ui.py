"""Maturity and Rollover as Drafts in the Obligacje tab and the header (L-6, spec 3.4.1)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.bonds import SeriesTerms
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.bond_data import save_series_terms
from financial_app.persistence.bond_series import series_instrument
from financial_app.persistence.db import init_db
from financial_app.persistence.settings import VIEW_SCOPE, save_setting
from financial_app.persistence.transactions import add_transaction, list_transactions
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell

NBSP = "\xa0"
TODAY = date(2026, 10, 8)


def _terms(name: str, sold: date) -> SeriesTerms:
    rates = (Decimal("0.03"),) * 10
    return SeriesTerms(name, "PL0000119145", sold, sold, Decimal(100), Decimal("99.9"), Decimal("0.01"), rates, ())


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = init_db(tmp_path / "app.sqlite3")
    save_series_terms(engine, [_terms("EDO0626", date(2016, 6, 1)), _terms("EDO0636", date(2026, 6, 1))])
    return engine


def _bought(engine: Engine, name: str, account_type: AccountType = AccountType.BONDS) -> int:
    account = add_account(engine, AccountDraft(name, "PKO BP", account_type, ("PLN",)))
    instrument, _ = series_instrument(engine, "EDO0626")
    day = date(2016, 6, 15)
    add_transaction(engine, TransactionDraft(account.id, day, TransactionType.DEPOSIT, Decimal(1000)))
    add_transaction(engine, buy_or_sell(account.id, day, TransactionType.BUY, instrument.id, Decimal(10), Decimal(100)))
    return account.id


def _shell(engine: Engine) -> None:
    build_shell(engine, NbpRates(engine, fetch=lambda url: None, today=lambda: TODAY))


async def _open(user: User) -> None:
    await user.open("/obligacje")
    await user.should_see(marker="bond-drafts")


async def test_a_matured_lot_is_a_draft_counted_in_the_header_and_confirmed_as_its_redemption(engine: Engine) -> None:
    _bought(engine, "Obligacje")

    async with user_simulation(lambda: _shell(engine)) as user:
        await _open(user)
        await user.should_see(marker="drafts-count", content="Do zatwierdzenia: 1")
        with user.scope(marker="bond-draft"):
            await user.should_see("Wykup EDO0626")
            await user.should_see("wykup 15.06.2026")
            await user.should_see(f"Wypłata netto 1{NBSP}278,60{NBSP}zł")

        user.find(marker="confirm-redemption").click()

        await user.should_not_see(marker="bond-drafts")
        await user.should_not_see(marker="drafts-count")
        await user.should_see(marker="bonds-empty")
    sell = list_transactions(engine)[0]
    assert (sell.transaction_type, sell.date, sell.lot_id) == (TransactionType.SELL, date(2026, 6, 15), 2)


async def test_a_confirmed_draft_warns_like_any_other_save(engine: Engine) -> None:
    account = _bought(engine, "Obligacje")
    add_transaction(engine, TransactionDraft(account, date(2026, 7, 1), TransactionType.WITHDRAWAL, Decimal(1500)))

    async with user_simulation(lambda: _shell(engine)) as user:
        await _open(user)
        user.find(marker="confirm-redemption").click()

        await user.should_see(f"Zapisano, ale Saldo gotówki konta Obligacje jest ujemne: -221,40{NBSP}zł.")


async def test_a_rollover_redeems_the_lot_and_buys_the_new_series(engine: Engine) -> None:
    _bought(engine, "Obligacje")

    async with user_simulation(lambda: _shell(engine)) as user:
        await _open(user)
        user.find(marker="rollover").click()
        with user.scope(marker="rollover-dialog"):
            await user.should_see(f"Seria EDO0636 · cena zamiany 99,90{NBSP}zł · zakup 15.06.2026")
        user.find(marker="save-rollover").click()

        await user.should_not_see(marker="bond-drafts")
        with user.scope(marker="bonds"):
            await user.should_see("EDO0636")
    buy, sell = list_transactions(engine)[:2]
    assert (buy.transaction_type, buy.quantity, buy.actual_amount) == (
        TransactionType.BUY,
        Decimal(10),
        Decimal("999.00"),
    )
    assert sell.transaction_type is TransactionType.SELL


async def test_the_list_follows_the_view_scope_while_the_header_counts_every_account(engine: Engine) -> None:
    _bought(engine, "Obligacje")
    ike = add_account(engine, AccountDraft("IKE", "PKO BP", AccountType.IKE, ("PLN",)))
    save_setting(engine, VIEW_SCOPE, str(ike.id))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/obligacje")

        await user.should_see(marker="drafts-count", content="Do zatwierdzenia: 1")
        await user.should_not_see(marker="bond-drafts")


def _coi_bought(engine: Engine) -> None:
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


async def test_each_coupon_paid_is_a_draft_confirmed_as_interest(engine: Engine) -> None:
    _coi_bought(engine)

    async with user_simulation(lambda: _shell(engine)) as user:
        await _open(user)
        await user.should_see(marker="drafts-count", content="Do zatwierdzenia: 2")
        await user.should_see("Odsetki COI0528")
        await user.should_see("okres 1 · 20.05.2025")
        await user.should_see(f"Wypłata netto 53,10{NBSP}zł")
        await user.should_see(f"Wypłata netto 49,80{NBSP}zł")

        user.find(marker="confirm-coupon").click()

        await user.should_see(marker="drafts-count", content="Do zatwierdzenia: 1")
        await user.should_not_see("okres 1 · 20.05.2025")
        await user.should_see("okres 2 · 20.05.2026")

        # Matching the bank statement keeps the coupon entered
        await user.open("/transakcje")
        await user.should_see("Odsetki COI0528")
        user.find(marker="transaction-row").click()  # the newest, the interest
        user.find(marker="transaction-withholding-tax").clear().type("12,45")
        user.find("Zapisz zmiany").click()
        await user.should_see(marker="drafts-count", content="Do zatwierdzenia: 1")

    [interest] = [t for t in list_transactions(engine) if t.transaction_type is TransactionType.DIVIDEND]
    assert (interest.date, interest.withholding_tax, interest.lot_id) == (date(2025, 5, 20), Decimal("12.45"), 2)
