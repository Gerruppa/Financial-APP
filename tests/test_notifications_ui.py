"""UI tests of the header bell (issue #176): what it lists, its dot and the read state."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.recurring import Frequency, RecurringRuleDraft
from financial_app.domain.term_deposits import Capitalization, TermDepositDraft, TermUnit
from financial_app.domain.transactions import TransactionType
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.recurring_rules import add_rule
from financial_app.persistence.settings import UI_NOTIFICATIONS_READ, load_setting
from financial_app.persistence.term_deposits import add_deposit
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell

TODAY = date(2026, 10, 15)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _shell(engine: Engine) -> None:
    build_shell(engine, NbpRates(engine, fetch=lambda url: None, today=lambda: TODAY))


def _add_rule(engine: Engine) -> None:
    account = add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN",))).id
    add_rule(
        engine,
        RecurringRuleDraft(
            name="Wpłata IKE",
            account_id=account,
            transaction_type=TransactionType.DEPOSIT,
            amount=Decimal(1000),
            currency="PLN",
            frequency=Frequency.MONTHLY,
            day_of_month=10,
            start_date=date(2026, 9, 1),
        ),
    )


async def test_the_bell_has_nothing_to_remind_of_in_an_empty_app(engine: Engine) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")
        await user.should_see(marker="notifications-bell")
        await user.should_see(marker="notifications-empty")
        await user.should_not_see(marker="notifications-dot")


async def test_due_drafts_light_the_dot_until_the_bell_is_opened(engine: Engine) -> None:
    _add_rule(engine)
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")
        await user.should_see(marker="notifications-dot")
        await user.should_see(marker="notification-unread")
        await user.should_see("Transakcje cykliczne do zatwierdzenia: 2")

        user.find(marker="notifications-bell").click()

        await user.should_not_see(marker="notifications-dot")
    assert load_setting(engine, UI_NOTIFICATIONS_READ) is not None


async def test_a_read_reminder_stays_read_in_a_new_window_until_it_changes(engine: Engine) -> None:
    _add_rule(engine)
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")
        user.find(marker="notifications-bell").click()
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")
        await user.should_not_see(marker="notifications-dot")
        await user.should_see(marker="notification")
        await user.should_see("Transakcje cykliczne do zatwierdzenia: 2")


async def test_a_deposit_maturing_soon_is_announced(engine: Engine) -> None:
    account = add_account(engine, AccountDraft("Bank", "Bank", AccountType.DEPOSIT, ("PLN",))).id
    add_deposit(
        engine,
        TermDepositDraft(
            account, "Lokata Jesień", Decimal(10000), date(2026, 9, 5), 2, TermUnit.MONTHS, Decimal(5),
            Capitalization.AT_MATURITY,
        ),
    )  # fmt: skip
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")
        await user.should_see("Zapada 05.11.2026: Lokata Jesień")
