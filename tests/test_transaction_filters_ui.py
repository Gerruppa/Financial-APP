"""The Transakcje headers sorting and filtering the list, "wyczyść filtry" and the filtered export (L-27)."""

import asyncio
import contextlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.transactions import TransactionDraft, TransactionType, cash_transfer
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.settings import VIEW_SCOPE, save_setting
from financial_app.persistence.transactions import add_transactions
from financial_app.ui.shell import build_shell


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def accounts(engine: Engine) -> tuple[int, int]:
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    xtb = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id
    add_transactions(
        engine,
        [
            TransactionDraft(ike, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(1000), comment="Wpłata IKE"),
            TransactionDraft(xtb, date(2026, 8, 4), TransactionType.DEPOSIT, Decimal(3000), comment="wpłata XTB"),
            TransactionDraft(xtb, date(2026, 9, 1), TransactionType.WITHDRAWAL, Decimal(200), comment="wypłata"),
            cash_transfer(xtb, date(2026, 10, 5), ike, Decimal(500), comment="przelew"),
        ],
    )
    return ike, xtb


ALL = ["przelew", "wypłata", "wpłata XTB", "Wpłata IKE"]


def _comments(user: User) -> list[str]:
    """The listed Transactions' comments top to bottom."""
    rows = sorted(user.find(marker="transaction-row").elements, key=lambda element: element.id)
    return [[d.text for d in row.descendants() if isinstance(d, ui.label)][-1] for row in rows]


async def _shows(user: User, comments: list[str]) -> None:
    """Waits for the list (redrawn in the background) to show these comments top to bottom."""
    for _ in range(100):
        with contextlib.suppress(AssertionError):  # no rows while the list is redrawn
            if _comments(user) == comments:
                return
        await asyncio.sleep(0.01)
    assert _comments(user) == comments


async def _open(user: User) -> None:
    await user.open("/transakcje")
    await user.should_see(marker="transaction-row")


async def test_the_date_header_turns_the_order_round(engine: Engine, accounts: tuple[int, int]) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await _open(user)
        await _shows(user, ["przelew", "wypłata", "wpłata XTB", "Wpłata IKE"])
        assert user.find(marker="sort-date").elements.pop().props["icon-right"] == "arrow_downward"

        user.find(marker="sort-date").click()

        await _shows(user, ["Wpłata IKE", "wpłata XTB", "wypłata", "przelew"])
        assert user.find(marker="sort-date").elements.pop().props["icon-right"] == "arrow_upward"


async def test_another_header_sorts_by_its_column(engine: Engine, accounts: tuple[int, int]) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await _open(user)

        user.find(marker="sort-amount").click()

        await _shows(user, ["wpłata XTB", "Wpłata IKE", "przelew", "wypłata"])
        assert "icon-right" not in user.find(marker="sort-date").elements.pop().props


async def test_an_account_filter_keeps_the_ticked_accounts_and_shows_as_active(
    engine: Engine, accounts: tuple[int, int]
) -> None:
    ike, _ = accounts
    async with user_simulation(lambda: build_shell(engine)) as user:
        await _open(user)
        user.find(marker="filter-account").click()
        await user.should_see(marker="filter-all-account")

        user.find(marker=f"filter-option-account-{ike}").click()

        await _shows(user, ["przelew", "wypłata", "wpłata XTB"])
        await user.should_see(marker="filter-active")
        await user.should_see(marker="clear-filters")


async def test_amount_and_comment_filters_combine(engine: Engine, accounts: tuple[int, int]) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await _open(user)
        user.find(marker="filter-amount").click()
        await user.should_see(marker="filter-amount-od")
        user.find(marker="filter-amount-od").type("500")
        user.find(marker="filter-amount-do").type("1 000,00")
        await _shows(user, ["przelew", "Wpłata IKE"])

        user.find(marker="filter-comment").click()
        await user.should_see(marker="filter-comment-text")
        user.find(marker="filter-comment-text").type("WPŁ")

        await _shows(user, ["Wpłata IKE"])


async def test_an_unreadable_range_end_leaves_the_list(engine: Engine, accounts: tuple[int, int]) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await _open(user)
        user.find(marker="filter-date").click()
        await user.should_see(marker="filter-date-od")

        user.find(marker="filter-date-od").type("1.9")

        await _shows(user, ALL)
        user.find(marker="filter-date-od").clear().type("01.09.2026")
        await _shows(user, ["przelew", "wypłata"])


async def test_nothing_matching_says_so_and_clearing_shows_everything(
    engine: Engine, accounts: tuple[int, int]
) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await _open(user)
        user.find(marker="filter-comment").click()
        await user.should_see(marker="filter-comment-text")
        user.find(marker="filter-comment-text").type("nic takiego")
        await user.should_see(marker="no-match")

        user.find(marker="clear-filters").click()

        await _shows(user, ALL)
        await user.should_not_see(marker="filter-active")
        await user.should_not_see(marker="clear-filters")


async def test_filters_combine_with_the_view_scope_and_the_export_holds_the_filtered_list(
    engine: Engine, accounts: tuple[int, int]
) -> None:
    ike, _ = accounts
    save_setting(engine, VIEW_SCOPE, str(ike))
    async with user_simulation(lambda: build_shell(engine)) as user:
        await _open(user)
        await _shows(user, ["przelew", "Wpłata IKE"])
        user.find(marker="filter-type").click()
        await user.should_see(marker="filter-all-type")
        user.find(marker=f"filter-option-type-{TransactionType.CASH_TRANSFER}").click()
        await _shows(user, ["Wpłata IKE"])

        user.find("Eksportuj CSV").click()
        response = await user.download.next()

    lines = response.content.decode("utf-8-sig").splitlines()
    assert [line.split(";")[-1] for line in lines[1:]] == ["Wpłata IKE"]
