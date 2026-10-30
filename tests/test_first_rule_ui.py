"""Ustawienia > Limity i reguły: the first Recurring Rule's step-by-step window with examples (#275)."""

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.recurring import Frequency, RecurringRuleDraft
from financial_app.domain.transactions import TransactionType
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.recurring_rules import add_rule, list_rules
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell

TODAY = date(2026, 10, 15)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def accounts(engine: Engine) -> tuple[int, int]:
    regular = add_account(engine, AccountDraft("Maklerskie", "XTB", AccountType.REGULAR, ("PLN",))).id
    ike = add_account(engine, AccountDraft("Moje IKE", "XTB", AccountType.IKE, ("PLN",))).id
    return regular, ike


@pytest.fixture
async def user(engine: Engine) -> AsyncIterator[User]:
    shell = lambda: build_shell(engine, NbpRates(engine, fetch=lambda url: None, today=lambda: TODAY))  # noqa: E731
    async with user_simulation(shell) as user:
        await user.open("/ustawienia")
        yield user


def choose(user: User, marker: str, value: object) -> None:
    for element in user.find(marker=marker).elements:
        assert isinstance(element, ui.radio | ui.select)
        element.value = value


def value(user: User, marker: str) -> object:
    return user.find(marker=marker, kind=ui.select | ui.input).elements.pop().value  # type: ignore[arg-type]


async def test_the_ike_deposit_example_is_saved_with_its_next_drafts(
    user: User, engine: Engine, accounts: tuple[int, int]
) -> None:
    user.find(marker="first-rule-open").click()
    await user.should_see(marker="first-rule-step-1")
    choose(user, "first-rule-example", "deposit")
    user.find(marker="first-rule-next").click()
    await user.should_see(marker="first-rule-step-2")
    # The example pre-fills the rule, on the IKE Account
    assert value(user, "first-rule-account") == accounts[1]
    assert value(user, "first-rule-amount") == "500,00"
    assert value(user, "first-rule-day") == "10"
    assert value(user, "first-rule-start") == "10.11.2026"
    user.find(marker="first-rule-next").click()
    await user.should_see(marker="first-rule-step-3")
    # The next Drafts; 10.01.2027 is a Sunday, moved to Monday
    for day in ("10.11.2026", "10.12.2026", "11.01.2027"):
        await user.should_see(day)
    await user.should_see(marker="first-rule-drafts-note")
    user.find(marker="first-rule-save").click()
    await user.should_see(marker="first-rule-done")
    [rule] = list_rules(engine)
    assert (rule.name, rule.account_id, rule.transaction_type, rule.amount, rule.day_of_month) == (
        "Wpłata IKE",
        accounts[1],
        TransactionType.DEPOSIT,
        Decimal(500),
        10,
    )
    assert (rule.frequency, rule.start_date) == (Frequency.MONTHLY, date(2026, 11, 10))
    # The window is offered only while there is no rule
    await user.should_see(marker="recurring-rule")
    await user.should_not_see(marker="first-rule-open")


async def test_the_cash_transfer_example_names_both_accounts(
    user: User, engine: Engine, accounts: tuple[int, int]
) -> None:
    user.find(marker="first-rule-open").click()
    choose(user, "first-rule-example", "transfer")
    user.find(marker="first-rule-next").click()
    await user.should_see(marker="first-rule-step-2")
    assert (value(user, "first-rule-account"), value(user, "first-rule-target")) == accounts
    user.find(marker="first-rule-next").click()
    await user.should_see("Maklerskie → Moje IKE")


async def test_a_buy_without_an_instrument_cannot_be_saved(user: User, accounts: tuple[int, int]) -> None:
    user.find(marker="first-rule-open").click()
    choose(user, "first-rule-example", "etf")
    user.find(marker="first-rule-next").click()
    await user.should_see(marker="first-rule-instrument")
    user.find(marker="first-rule-next").click()
    await user.should_see("Wybierz instrument.")
    assert not user.find(marker="first-rule-save", kind=ui.button).elements.pop().enabled


async def test_with_a_rule_the_window_is_not_offered(engine: Engine, accounts: tuple[int, int]) -> None:
    draft = RecurringRuleDraft(
        "Wpłata", accounts[1], TransactionType.DEPOSIT, Decimal(100), "PLN", Frequency.MONTHLY, 10, date(2026, 11, 1)
    )
    add_rule(engine, draft)
    async with user_simulation(
        lambda: build_shell(engine, NbpRates(engine, fetch=lambda url: None, today=lambda: TODAY))
    ) as user:
        await user.open("/ustawienia")
        await user.should_see(marker="recurring-rule")
        await user.should_not_see(marker="first-rule-open")


async def test_the_first_occurrence_follows_the_day_until_typed(user: User, accounts: tuple[int, int]) -> None:
    user.find(marker="first-rule-open").click()
    user.find(marker="first-rule-next").click()
    await user.should_see(marker="first-rule-step-2")
    day = user.find(marker="first-rule-day")
    day.clear()
    day.type("25")
    # 25.10.2026 is a Sunday
    assert value(user, "first-rule-start") == "26.10.2026"
    start = user.find(marker="first-rule-start")
    start.clear()
    start.type("01.12.2026")
    day.clear()
    day.type("5")
    assert value(user, "first-rule-start") == "01.12.2026"
