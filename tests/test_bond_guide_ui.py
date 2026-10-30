"""The bond help window (issue #272), opened from the "+" dialog's bond mode and from the Rollover dialog: the series
codes, the chosen Series' periods with their rates and sources, the Rollover and what to check on the statement."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.bonds import BondType, SeriesTerms
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account, list_accounts
from financial_app.persistence.bond_data import save_series_terms
from financial_app.persistence.bond_series import series_instrument
from financial_app.persistence.db import init_db
from financial_app.persistence.transactions import add_transaction
from financial_app.sources.nbp import NbpRates
from financial_app.ui.bond_guide import TYPE_HELP
from financial_app.ui.shell import build_shell

NBSP = "\xa0"
TODAY = date(2026, 10, 8)


def _terms(name: str, sold: date, first: str) -> SeriesTerms:
    rates = (Decimal(first), *(Decimal("0.03"),) * 9)
    return SeriesTerms(name, "PL0000119145", sold, sold, Decimal(100), Decimal("99.9"), Decimal("0.02"), rates, ())


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = init_db(tmp_path / "app.sqlite3")
    save_series_terms(
        engine,
        [
            _terms("EDO0626", date(2016, 6, 1), "0.03"),
            _terms("EDO0636", date(2026, 6, 1), "0.0560"),
            _terms("EDO1036", date(2026, 10, 1), "0.0535"),
        ],
    )
    add_account(engine, AccountDraft("Obligacje", "PKO BP", AccountType.BONDS, ("PLN",)))
    return engine


@pytest.fixture
def matured(engine: Engine) -> Engine:
    """A Lot of EDO0626 matured on 15.06.2026, a Rollover Draft."""
    [account] = [a.id for a in list_accounts(engine)]
    instrument, _ = series_instrument(engine, "EDO0626")
    day = date(2016, 6, 15)
    add_transaction(engine, TransactionDraft(account, day, TransactionType.DEPOSIT, Decimal(1000)))
    add_transaction(engine, buy_or_sell(account, day, TransactionType.BUY, instrument.id, Decimal(10), Decimal(100)))
    return engine


def _shell(engine: Engine) -> None:
    build_shell(engine, NbpRates(engine, fetch=lambda url: None, today=lambda: TODAY))


def test_every_bond_type_is_explained() -> None:
    assert set(TYPE_HELP) == set(BondType)


async def test_the_help_opens_from_the_bond_purchase_with_the_chosen_series_periods(engine: Engine) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="add-transaction").click()
        user.find(marker="transaction-type").click()
        user.find("Zakup").click()
        user.find(marker="transaction-date").clear().type("12.10.2026")
        await user.should_see("Seria EDO1036")

        user.find(marker="transaction-bond-help").click()

        with user.scope(marker="bond-guide"):
            await user.should_see("Okresy odsetkowe serii EDO1036")
            await user.should_see(f"Rok 1 · 12.10.2026–12.10.2027 · 5,35{NBSP}% · z pliku MF")
            await user.should_see("Rok 10 · 12.10.2035–12.10.2036")
            await _sees_the_general_help(user)


async def test_the_help_opens_from_the_rollover_with_the_new_series_from_the_maturity_day(matured: Engine) -> None:
    async with user_simulation(lambda: _shell(matured)) as user:
        await user.open("/obligacje")
        user.find(marker="rollover").click()

        user.find(marker="rollover-help").click()

        with user.scope(marker="bond-guide"):
            await user.should_see("Okresy odsetkowe serii EDO0636")
            await user.should_see(f"Rok 1 · 15.06.2026–15.06.2027 · 5,60{NBSP}% · z pliku MF")
            await _sees_the_general_help(user)


async def _sees_the_general_help(user: User) -> None:
    await user.should_see("Rodzaje obligacji")
    await user.should_see("Zamiana (rolowanie)")
    await user.should_see("Co sprawdzić z wyciągiem")
