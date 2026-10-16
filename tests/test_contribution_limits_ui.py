"""Contribution Limits (issue #95, spec 8.1): the Dashboard's bars, the limits in Ustawienia and the warning after a
save."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.transactions import TransactionDraft, TransactionType
from financial_app.persistence.accounts import add_account
from financial_app.persistence.contribution_limits import load_limits
from financial_app.persistence.db import init_db
from financial_app.persistence.transactions import add_transaction
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
TODAY = date(2026, 10, 8)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """IKE with 28 000 PLN paid in this year, IKZE with nothing, and a Regular Account."""
    engine = init_db(tmp_path / "app.sqlite3")
    ike = add_account(engine, AccountDraft("XTB IKE", "XTB", AccountType.IKE, ("PLN",))).id
    add_account(engine, AccountDraft("XTB IKZE", "XTB", AccountType.IKZE, ("PLN",)))
    regular = add_account(engine, AccountDraft("mBank", "mBank", AccountType.REGULAR, ("PLN",))).id
    add_transaction(engine, TransactionDraft(ike, date(2026, 2, 1), TransactionType.DEPOSIT, Decimal(28000)))
    add_transaction(engine, TransactionDraft(regular, date(2026, 2, 1), TransactionType.DEPOSIT, Decimal(50000)))
    return engine


def _shell(engine: Engine) -> None:
    build_shell(engine, NbpRates(engine, fetch=lambda url: None, today=lambda: TODAY))


def _pln(text: str) -> str:
    return f"{text.replace(' ', NBSP)}{NBSP}zł"


async def test_the_dashboard_shows_this_years_bar_per_type_and_an_accounts_scope_only_its_own(engine: Engine) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")

        with user.scope(marker="contribution-limits"):
            await user.should_see("Limity wpłat 2026")
        with user.scope(marker="limit-bar-ike"):
            await user.should_see(f"{_pln('28 000,00')} z {_pln('28 260,00')}")
            await user.should_see(f"Pozostało {_pln('260,00')}")
        with user.scope(marker="limit-bar-ikze"):
            await user.should_see(f"{_pln('0,00')} z {_pln('11 304,00')}")
        await user.should_not_see(marker="limit-bar-oipe")

        user.find(marker="view-scope").click()
        await user.should_see(marker="scope-menu")
        user.find(marker="scope-1").click()

        await user.should_see("łącznie na wszystkich kontach IKE")
        await user.should_not_see(marker="limit-bar-ikze")

        user.find(marker="view-scope").click()
        await user.should_see(marker="scope-menu")
        user.find(marker="scope-3").click()

        await user.should_not_see(marker="contribution-limits")


async def test_a_limit_edited_in_ustawienia_moves_the_bar_and_a_year_is_added_and_removed(engine: Engine) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/ustawienia")
        await user.should_see(marker="limit-paid-2026-ike", content=f"wpłacono {_pln('28 000,00')}")

        user.find(marker="limit-2026-ike").clear().type("27 000")
        user.find(marker="limits-save-2026").click()
        user.find(marker="limits-add-year").click()
        await user.should_see(marker="limit-2027-ike")
        user.find(marker="limits-delete-2027").click()
        await user.should_not_see(marker="limit-2027-ike")

        await user.open("/")
        with user.scope(marker="limit-bar-ike"):
            await user.should_see(f"Przekroczono limit o {_pln('1 000,00')}")
    assert load_limits(engine)[2026][AccountType.IKE] == Decimal(27000)
    assert list(load_limits(engine)) == [2026]


async def test_any_earlier_year_can_be_added_but_not_one_that_is_no_year(engine: Engine) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/ustawienia")
        await user.should_see(marker="limits-new-year")

        user.find(marker="limits-new-year").clear().type("dwa tysiące")
        user.find(marker="limits-add-year").click()
        await user.should_see("Rok podaj czterema cyframi, np. 2025.")

        user.find(marker="limits-new-year").clear().type("2025")
        user.find(marker="limits-add-year").click()
        await user.should_see(marker="limit-2025-ike")
    assert list(load_limits(engine)) == [2025, 2026]


async def test_a_limit_that_is_no_amount_is_refused(engine: Engine) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/ustawienia")
        await user.should_see(marker="limit-2026-ike")

        user.find(marker="limit-2026-ike").clear().type("-5")
        user.find(marker="limits-save-2026").click()

        await user.should_see("Limit musi być kwotą w zł, nie mniejszą od zera.")
    assert load_limits(engine)[2026][AccountType.IKE] == Decimal(28260)


async def test_saving_a_deposit_over_the_limit_warns_but_saves(engine: Engine) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="add-transaction").click()
        user.find(marker="transaction-account", kind=ui.select).elements.pop().set_value(1)
        user.find(marker="transaction-date").clear().type("08.10.2026")
        user.find(marker="transaction-amount").type("1 000")
        user.find("Zapisz").click()

        await user.should_see(f"IKE 2026: przekroczono limit wpłat o {_pln('740,00')}.")
