"""The Dochód pasywny tab (issue #93, spec 10): income received and coupons forecast by month, with the Monthly Income
Goal."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.bonds import SeriesTerms
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell, dividend
from financial_app.persistence.accounts import add_account
from financial_app.persistence.bond_data import save_series_terms
from financial_app.persistence.bond_series import series_instrument
from financial_app.persistence.db import init_db
from financial_app.persistence.settings import PASSIVE_INCOME_GOAL, load_setting
from financial_app.persistence.transactions import add_transaction
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
TODAY = date(2026, 10, 8)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """Obligacje: 10 COI0528 bought on 20.05.2024, its coupons of 20.05.2025 (53,10 PLN net) and 20.05.2026
    (49,80 PLN net) not entered; XTB: 8 PLN of interest net on 15.01.2026."""
    engine = init_db(tmp_path / "app.sqlite3")
    rates = (Decimal("0.0655"), Decimal("0.0615"), None, None)
    terms = SeriesTerms(
        "COI0528", "PL0000119145", date(2024, 5, 1), date(2024, 5, 31), Decimal(100), Decimal("99.9"),
        Decimal("0.0125"), rates, (),
    )  # fmt: skip
    save_series_terms(engine, [terms])
    bonds = add_account(engine, AccountDraft("Obligacje", "PKO BP", AccountType.BONDS, ("PLN",))).id
    xtb = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id
    instrument, _ = series_instrument(engine, "COI0528")
    day = date(2024, 5, 20)
    add_transaction(engine, TransactionDraft(bonds, day, TransactionType.DEPOSIT, Decimal(1000)))
    add_transaction(engine, buy_or_sell(bonds, day, TransactionType.BUY, instrument.id, Decimal(10), Decimal(100)))
    add_transaction(engine, dividend(xtb, date(2026, 1, 15), Decimal(10), Decimal(2)))
    return engine


def _shell(engine: Engine) -> None:
    build_shell(engine, NbpRates(engine, fetch=lambda url: None, today=lambda: TODAY))


def _month(user: User, index: int) -> list[str]:
    rows = sorted(user.find(marker="income-month").elements, key=lambda element: element.id)
    return [d.text for d in rows[index].descendants() if isinstance(d, ui.label)]


def _pln(text: str) -> str:
    return f"{text}{NBSP}zł"


async def test_the_year_shows_the_income_received_and_the_coupons_forecast(engine: Engine) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/dochod-pasywny")

        await user.should_see(marker="income-year", content="2026")
        await user.should_see(marker="income-year-received", content=_pln("8,00"))
        await user.should_see(marker="income-year-forecast", content=_pln("49,80"))
        assert _month(user, 0)[:4] == ["Styczeń", _pln("8,00"), _pln("0,00"), _pln("8,00")]
        assert _month(user, 4)[:4] == ["Maj", _pln("0,00"), _pln("49,80"), _pln("49,80")]
        with user.scope(marker="income-forecast"):
            await user.should_see("20.05.2026 (do zatwierdzenia)")
        await user.should_see(marker="chart-passive-income")

        user.find(marker="income-year-prev").click()

        await user.should_see(marker="income-year", content="2025")
        await user.should_see(marker="income-year-forecast", content=_pln("53,10"))


async def test_the_monthly_goal_is_saved_and_each_month_shows_its_progress(engine: Engine) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/dochod-pasywny")
        await user.should_see(marker="income-goal")

        user.find(marker="income-goal").type("40")
        user.find(marker="income-goal-save").click()

        await user.should_see(marker="income-monthly-goal", content=_pln("40,00"))
        assert _month(user, 0)[4] == f"20{NBSP}%"
        assert _month(user, 4)[4] == f"125{NBSP}%"
    assert load_setting(engine, PASSIVE_INCOME_GOAL) == "40"


async def test_a_goal_that_is_no_amount_is_refused(engine: Engine) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/dochod-pasywny")
        await user.should_see(marker="income-goal")

        user.find(marker="income-goal").type("dużo")
        user.find(marker="income-goal-save").click()

        await user.should_see("Cel musi być kwotą w zł.")
    assert load_setting(engine, PASSIVE_INCOME_GOAL) is None


async def test_an_account_scope_keeps_its_own_income(engine: Engine) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/dochod-pasywny")
        await user.should_see(marker="income-month")
        user.find(marker="view-scope").click()
        await user.should_see(marker="scope-menu")
        user.find(marker="scope-2").click()

        await user.should_see(marker="income-year-forecast", content=_pln("0,00"))
        await user.should_see(marker="income-year-received", content=_pln("8,00"))
