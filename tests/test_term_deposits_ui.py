"""Term Deposits in the Dochód stały tab (issue #160): adding one, its list, and its Drafts confirmed, ended, renewed
or broken."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.term_deposits import Capitalization, TermDepositDraft, TermUnit
from financial_app.domain.transactions import TransactionType, deposit_or_withdrawal
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.term_deposits import add_deposit, list_deposits
from financial_app.persistence.transactions import add_transaction, list_transactions
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell

NBSP = "\xa0"
TODAY = date(2026, 3, 1)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def account(engine: Engine) -> int:
    return add_account(engine, AccountDraft("Lokaty mBank", "mBank", AccountType.DEPOSIT, ("PLN",))).id


def _shell(engine: Engine) -> None:
    build_shell(engine, NbpRates(engine, fetch=lambda url: None, today=lambda: TODAY))


def _type(user: User, marker: str, text: str) -> None:
    field = user.find(marker=marker)
    field.clear()
    field.type(text)


def _choose(user: User, marker: str, value: object) -> None:
    for element in user.find(marker=marker).elements:
        assert isinstance(element, ui.select)
        element.value = value


def _three_months(account_id: int, **fields: object) -> TermDepositDraft:
    values: dict[str, object] = {
        "account_id": account_id,
        "name": "Lokata 3M",
        "principal": Decimal(10000),
        "start_date": date(2026, 1, 15),
        "term_count": 3,
        "term_unit": TermUnit.MONTHS,
        "annual_rate": Decimal(6),
        "capitalization": Capitalization.MONTHLY,
    }
    values.update(fields)
    return TermDepositDraft(**values)  # type: ignore[arg-type]


def _paid_in(engine: Engine, account_id: int, amount: int = 10000) -> None:
    add_transaction(
        engine, deposit_or_withdrawal(account_id, date(2026, 1, 15), TransactionType.DEPOSIT, Decimal(amount))
    )


async def test_a_deposit_is_added_with_its_capital_paid_in_and_listed_with_its_accrued_interest(
    engine: Engine, account: int
) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/obligacje")
        await user.should_see(marker="deposits-empty")
        user.find(marker="add-deposit").click()
        with user.scope(marker="deposit-dialog"):
            _type(user, "deposit-name", "Lokata 3M")
            _type(user, "deposit-principal", "10000")
            _type(user, "deposit-start", "15.01.2026")
            _type(user, "deposit-term", "3")
            _type(user, "deposit-rate", "6")
            _choose(user, "deposit-capitalization", Capitalization.MONTHLY.value)
            _choose(user, "deposit-capital", "deposit")
            await user.should_see(f"Zapadalność 15.04.2026 · odsetki netto na koniec 120,32{NBSP}zł")
            user.find(marker="save-deposit").click()

        await user.should_see(marker="deposit-row")
        with user.scope(marker="deposit-row"):
            await user.should_see("Lokata 3M")
            await user.should_see("15.04.2026")
            await user.should_see(f"60,00{NBSP}zł")
            await user.should_see(f"10{NBSP}041,28{NBSP}zł")
            await user.should_see(f"6,00{NBSP}%")
            await user.should_not_see(f"%{NBSP}%")
    (deposit,) = list_deposits(engine)
    assert (deposit.principal, deposit.capitalization) == (Decimal(10000), Capitalization.MONTHLY)
    (paid_in,) = list_transactions(engine)
    assert (paid_in.transaction_type, paid_in.date, paid_in.actual_amount) == (
        TransactionType.DEPOSIT,
        date(2026, 1, 15),
        Decimal(10000),
    )


async def test_an_ended_period_is_a_draft_counted_in_the_header_and_confirmed_as_linked_interest(
    engine: Engine, account: int
) -> None:
    _paid_in(engine, account)
    add_deposit(engine, _three_months(account))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/obligacje")
        await user.should_see(marker="drafts-count", content="Do zatwierdzenia: 1")
        with user.scope(marker="deposit-draft"):
            await user.should_see("Odsetki Lokata 3M")
            await user.should_see(f"Wypłata netto 41,28{NBSP}zł")
        user.find(marker="confirm-deposit-interest").click()

        await user.should_not_see(marker="bond-drafts")
        await user.should_not_see(marker="drafts-count")
    (_, interest) = sorted(list_transactions(engine), key=lambda t: t.date)
    assert (interest.date, interest.gross, interest.withholding_tax, interest.term_deposit_period) == (
        date(2026, 2, 15),
        Decimal("50.96"),
        Decimal("9.68"),
        date(2026, 2, 15),
    )


async def test_interest_is_edited_before_it_is_confirmed(engine: Engine, account: int) -> None:
    _paid_in(engine, account)
    add_deposit(engine, _three_months(account))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/obligacje")
        user.find(marker="edit-deposit-interest").click()
        with user.scope(marker="interest-dialog"):
            _type(user, "interest-gross", "50,97")
            _type(user, "interest-tax", "9,68")
            user.find(marker="save-interest").click()

        await user.should_not_see(marker="bond-drafts")
    interest = max(list_transactions(engine), key=lambda t: t.date)
    assert (interest.gross, interest.actual_amount, interest.term_deposit_id) == (
        Decimal("50.97"),
        Decimal("41.29"),
        list_deposits(engine)[0].id,
    )


async def test_a_matured_deposit_is_renewed_from_its_maturity_at_a_new_rate(engine: Engine, account: int) -> None:
    _paid_in(engine, account)
    add_deposit(engine, _three_months(account, start_date=date(2025, 11, 1), renew=True))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/obligacje")
        user.find(marker="renew-deposit").click()
        with user.scope(marker="renew-dialog"):
            _type(user, "renew-rate", "5,5")
            user.find(marker="save-renew").click()

        await user.should_not_see(marker="renew-deposit")
        with user.scope(marker="deposit-row"):
            await user.should_see("01.05.2026")
    old, new = list_deposits(engine)
    assert old.closed_on == date(2026, 2, 1)
    assert (new.start_date, new.annual_rate, new.renew) == (date(2026, 2, 1), Decimal("5.5"), True)


async def test_a_matured_deposit_is_ended_and_leaves_the_list(engine: Engine, account: int) -> None:
    _paid_in(engine, account)
    add_deposit(engine, _three_months(account, start_date=date(2025, 11, 1)))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/obligacje")
        user.find(marker="end-deposit").click()

        await user.should_see(marker="deposits-empty")
    assert list_deposits(engine)[0].closed_on == date(2026, 2, 1)


async def test_a_deposit_is_broken_from_its_dialog(engine: Engine, account: int) -> None:
    _paid_in(engine, account)
    add_deposit(engine, _three_months(account))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/obligacje")
        user.find(marker="deposit-row").click()
        with user.scope(marker="deposit-dialog"):
            _type(user, "deposit-break-date", "20.02.2026")
            user.find(marker="break-deposit").click()

        await user.should_see(marker="deposits-empty")
    assert list_deposits(engine)[0].closed_on == date(2026, 2, 20)


async def test_the_portfolio_counts_the_accrued_interest_in_the_accounts_value(engine: Engine, account: int) -> None:
    _paid_in(engine, account)
    add_deposit(engine, _three_months(account))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/portfolio")
        with user.scope(marker="account-accrued"):
            await user.should_see(f"60,00{NBSP}zł")
        await user.should_see(f"10{NBSP}060,00{NBSP}zł")
