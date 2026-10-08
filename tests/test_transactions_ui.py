"""Deposit and Withdrawal end to end (issue #11): "+" dialog, Transakcje list, Portfolio Cash Balance."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.transactions import TransactionDraft, TransactionType
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.transactions import add_transaction, list_transactions
from financial_app.ui.shell import build_shell

NBSP = "\xa0"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def ike(engine: Engine) -> int:
    return add_account(engine, AccountDraft("mBank IKE", "mBank", AccountType.IKE, ("PLN",))).id


def _save_transaction(user: User, *, type_label: str | None = None, amount: str, day: str = "05.10.2026") -> None:
    user.find(marker="add-transaction").click()
    if type_label is not None:
        user.find(marker="transaction-type").click()
        user.find(type_label).click()
    user.find(marker="transaction-date").clear().type(day)
    user.find(marker="transaction-amount").type(amount)
    user.find("Zapisz").click()


async def test_deposit_from_plus_dialog_appears_in_transakcje(engine: Engine, ike: int) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")

        _save_transaction(user, amount="1 000,5")

        with user.scope(marker="transactions"):
            await user.should_see("05.10.2026")
            await user.should_see("mBank IKE")
            await user.should_see("Wpłata")
            await user.should_see(f"+1{NBSP}000,50{NBSP}zł")
    [saved] = list_transactions(engine)
    assert (saved.account_id, saved.date, saved.transaction_type, saved.actual_amount) == (
        ike,
        date(2026, 10, 5),
        TransactionType.DEPOSIT,
        Decimal("1000.50"),
    )


async def test_withdrawal_is_listed_as_a_negative_amount(engine: Engine, ike: int) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")

        _save_transaction(user, type_label="Wypłata", amount="300")

        with user.scope(marker="transactions"):
            await user.should_see("Wypłata")
            await user.should_see(f"-300,00{NBSP}zł")


async def test_invalid_amount_is_reported_and_not_saved(engine: Engine, ike: int) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")

        _save_transaction(user, amount="dużo")

        await user.should_see("Kwota musi być liczbą")
    assert list_transactions(engine) == []


async def test_dialog_offers_only_active_accounts_holding_pln(engine: Engine, ike: int) -> None:
    add_account(engine, AccountDraft("Stare konto", "XTB", AccountType.REGULAR, ("PLN",), active=False))
    add_account(engine, AccountDraft("Konto USD", "IBKR", AccountType.REGULAR, ("USD",)))

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")
        user.find(marker="add-transaction").click()

        [account_select] = user.find(marker="transaction-account").elements
        assert isinstance(account_select, ui.select)
        assert list(account_select.options.values()) == ["mBank IKE"]  # type: ignore[union-attr]


async def test_dialog_without_accounts_points_to_ustawienia(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")
        user.find(marker="add-transaction").click()

        await user.should_see("Najpierw dodaj konto")


async def test_portfolio_card_shows_the_cash_balance(engine: Engine, ike: int) -> None:
    add_transaction(engine, TransactionDraft(ike, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal("1000")))
    add_transaction(engine, TransactionDraft(ike, date(2026, 1, 3), TransactionType.WITHDRAWAL, Decimal("300")))

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/portfolio")

        with user.scope(marker="portfolio"):
            await user.should_see("mBank IKE")
            await user.should_see("Saldo gotówki")
            await user.should_see(f"700,00{NBSP}zł")


async def test_portfolio_is_read_only(engine: Engine, ike: int) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/portfolio")

        with user.scope(marker="portfolio"):
            await user.should_see("mBank IKE")
            for kind in (ui.button, ui.input, ui.select, ui.checkbox, ui.switch):
                await user.should_not_see(kind=kind)


async def test_portfolio_updates_after_saving_a_deposit(engine: Engine, ike: int) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/portfolio")

        _save_transaction(user, amount="250")

        with user.scope(marker="portfolio"):
            await user.should_see(f"250,00{NBSP}zł")


async def test_withdrawal_beyond_the_cash_balance_saves_with_a_warning(engine: Engine, ike: int) -> None:
    add_transaction(engine, TransactionDraft(ike, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal("100")))

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")

        _save_transaction(user, type_label="Wypłata", amount="150")

        await user.should_see("Saldo gotówki konta mBank IKE jest ujemne")
    assert len(list_transactions(engine)) == 2


async def test_withdrawal_within_the_cash_balance_gives_no_warning(engine: Engine, ike: int) -> None:
    add_transaction(engine, TransactionDraft(ike, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal("100")))

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")

        _save_transaction(user, type_label="Wypłata", amount="100")

        await user.should_not_see("jest ujemne")
