"""Bond Series valued by the MF issue letters in the Portfolio and the Dashboard (L-3, spec 3.4.1): each Lot from its
purchase day, with the year's rate and a label when MF has not published it."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.bonds import CpiReading, SeriesTerms
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.bond_data import save_cpi, save_series_terms
from financial_app.persistence.bond_series import series_instrument
from financial_app.persistence.db import init_db
from financial_app.persistence.transactions import add_transaction
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell

NBSP = "\xa0"
TODAY = date(2026, 10, 8)


def _terms(series: str, rates: tuple[Decimal | None, ...]) -> SeriesTerms:
    """The Series sold in its maturity month ten years before."""
    year, month = 2000 + int(series[5:]) - 10, int(series[3:5])
    return SeriesTerms(
        series,
        "PL0000119145",
        date(year, month, 1),
        date(year, month, 28),
        Decimal(100),
        Decimal("99.9"),
        Decimal("0.02"),
        rates,
        (None,),
    )


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = init_db(tmp_path / "app.sqlite3")
    save_series_terms(
        engine,
        [_terms("EDO0536", (Decimal("0.0535"),) + (None,) * 9), _terms("EDO0535", (Decimal("0.0565"),) + (None,) * 9)],
    )
    return engine


def _bought(engine: Engine, series: str, day: date, quantity: int = 50) -> None:
    account = add_account(engine, AccountDraft(f"Obligacje {series}", "PKO BP", AccountType.BONDS, ("PLN",)))
    instrument, _ = series_instrument(engine, series)
    add_transaction(engine, TransactionDraft(account.id, day, TransactionType.DEPOSIT, Decimal(quantity * 100)))
    add_transaction(
        engine, buy_or_sell(account.id, day, TransactionType.BUY, instrument.id, Decimal(quantity), Decimal(100))
    )


def _shell(engine: Engine) -> None:
    build_shell(engine, NbpRates(engine, fetch=lambda url: None, today=lambda: TODAY))


async def test_the_portfolio_values_a_bond_series_with_its_rate(engine: Engine) -> None:
    _bought(engine, "EDO0536", date(2026, 5, 22))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/portfolio")

        with user.scope(marker="portfolio"):
            # 50 bonds of 102.04 zł after 139 days at 5.35%
            await user.should_see(f"5{NBSP}102,00{NBSP}zł")
            await user.should_see(f"102,04{NBSP}zł")
            await user.should_see(f"5,35{NBSP}% · rok 1")
            await user.should_not_see("do etapu 3")
            await user.should_not_see(marker="bond-rate-label")
        user.find(marker="position-row").click()
        with user.scope(marker="position-lots"):
            await user.should_see("Oprocentowanie")


async def test_a_year_without_an_mf_rate_is_estimated_from_cpi_and_labelled(engine: Engine) -> None:
    save_cpi(engine, [CpiReading(2026, 3, Decimal("103.0"), None)])
    _bought(engine, "EDO0535", date(2025, 5, 22))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/portfolio")

        with user.scope(marker="portfolio"):
            await user.should_see(f"5,00{NBSP}% · rok 2")
            await user.should_see("szacowana (CPI)")


async def test_a_series_without_its_first_rate_stays_at_cost_and_says_so(engine: Engine) -> None:
    _bought(engine, "EDO0636", date(2026, 6, 17))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/portfolio")

        with user.scope(marker="portfolio"):
            await user.should_see("brak oprocentowania")
            await user.should_see(f"5{NBSP}000,00{NBSP}zł")


async def test_the_dashboard_counts_the_bond_value(engine: Engine) -> None:
    _bought(engine, "EDO0536", date(2026, 5, 22))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")

        await user.should_see(marker="total-value", content=f"5{NBSP}102,00{NBSP}zł")
