"""The Investment Goal tile on the Dashboard (issue #96): set, edited and removed per View Scope, with its progress
and forecast."""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.investment_goal import GoalMode, InvestmentGoal
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.recurring import Frequency, RecurringRuleDraft
from financial_app.domain.transactions import TransactionDraft, TransactionType
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.investment_goals import load_goal, save_goal
from financial_app.persistence.recurring_rules import add_rule
from financial_app.persistence.transactions import add_transactions
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates
from financial_app.sources.portfolio_history import PortfolioHistory
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
TODAY = date(2026, 10, 17)
NOW = datetime(2026, 10, 17, 9, 0)


def _pln(text: str) -> str:
    return text.replace(" ", NBSP) + f"{NBSP}zł"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """IKE: 100 000 PLN in; XTB: 20 000 PLN in."""
    engine = init_db(tmp_path / "app.sqlite3")
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    xtb = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id
    add_transactions(
        engine,
        [
            TransactionDraft(ike, date(2025, 10, 1), TransactionType.DEPOSIT, Decimal(100000)),
            TransactionDraft(xtb, date(2026, 4, 1), TransactionType.DEPOSIT, Decimal(20000)),
        ],
    )
    return engine


async def _inline(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
    return function(*args)


def _shell(engine: Engine) -> Callable[[], None]:
    rates = NbpRates(engine, fetch=lambda url: None, today=lambda: TODAY)
    quotes = QuoteHistory(engine, lambda url: "Brak danych", lambda: TODAY, lambda: NOW, lambda url: None)
    history = PortfolioHistory(engine, quotes, rates, lambda: TODAY, _inline)
    return lambda: build_shell(engine, rates, now=lambda: NOW, history=history)


async def _switch_scope(user: User, marker: str) -> None:
    user.find(marker="view-scope").click()
    await user.should_see(marker="scope-menu")
    user.find(marker=marker).click()


async def test_a_goal_is_set_on_the_dashboard_and_shows_its_progress_and_forecast(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await user.should_see(marker="total-net-deposits", content=_pln("120 000,00"))

        user.find(marker="set-goal").click()
        await user.should_see(marker="goal-dialog")
        # The default monthly deposit: the 20 000 zł paid in over the last twelve months, per month
        await user.should_see(marker="goal-monthly-default", content=f"średnia z 12 miesięcy: {_pln('1 666,67')}")
        user.find(marker="goal-amount").type("1 000 000")
        user.find(marker="goal-save").click()

        await user.should_see(marker="goal-progress", content=f"Cel: {_pln('1 000 000,00')} · 12{NBSP}%")
        # 120 000 zł growing 4% a year with 1 666,67 zł a month: 268 months
        await user.should_see(marker="goal-forecast", content="Prognoza: cel w 02.2049")

    assert load_goal(engine, None) == InvestmentGoal(None, GoalMode.AMOUNT, amount=Decimal(1_000_000))


async def test_the_default_monthly_deposit_comes_from_the_recurring_rules_of_the_view(engine: Engine) -> None:
    # IKE: 3 000 zł a quarter in; 500 zł a month moved there from XTB
    add_rule(
        engine,
        RecurringRuleDraft(
            "IKE", 1, TransactionType.DEPOSIT, Decimal(3000), "PLN", Frequency.QUARTERLY, 10, date(2026, 11, 10)
        ),
    )
    add_rule(
        engine,
        RecurringRuleDraft(
            "Na IKE",
            2,
            TransactionType.CASH_TRANSFER,
            Decimal(500),
            "PLN",
            Frequency.MONTHLY,
            10,
            date(2026, 11, 10),
            target_account_id=1,
        ),
    )

    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await user.should_see(marker="total-net-deposits", content=_pln("120 000,00"))
        user.find(marker="set-goal").click()
        await user.should_see(marker="goal-dialog")
        await user.should_see(marker="goal-monthly-default", content=f"z reguł cyklicznych: {_pln('1 000,00')}")
        user.find(marker="goal-amount").type("1 000 000")
        user.find(marker="goal-save").click()
        await user.should_see(marker="goal-forecast", content=f"przy wpłatach {_pln('1 000,00')} miesięcznie")

        # IKE: its own Deposits and the Cash Transfers into it
        await _switch_scope(user, "scope-1")
        await user.should_see(marker="set-goal")
        user.find(marker="set-goal").click()
        await user.should_see(marker="goal-monthly-default", content=f"z reguł cyklicznych: {_pln('1 500,00')}")


async def test_a_fire_goal_already_reached_and_a_target_date_out_of_reach(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        user.find(marker="set-goal").click()
        await user.should_see(marker="goal-dialog")
        user.find(marker="goal-mode", kind=ui.toggle).elements.pop().set_value(GoalMode.FIRE.value)
        user.find(marker="goal-expenses").type("4 000")
        user.find(marker="goal-save").click()

        # 25 × 4 000 zł
        await user.should_see(marker="goal-progress", content=f"Cel: {_pln('100 000,00')} · 120{NBSP}%")
        await user.should_see(marker="goal-forecast", content="Cel osiągnięty")

        user.find(marker="edit-goal").click()
        await user.should_see(marker="goal-dialog")
        user.find(marker="goal-expenses").clear().type("400 000")
        user.find(marker="goal-target-date").type("17.10.2036")
        user.find(marker="goal-real-return").clear().type("0")
        user.find(marker="goal-monthly").type("0")
        user.find(marker="goal-save").click()

        await user.should_see(marker="goal-forecast", content="Poza zasięgiem")
        # 10 000 000 zł less 120 000 zł over 120 months
        await user.should_see(marker="goal-required", content=f"Do 17.10.2036 potrzeba {_pln('82 333,33')} miesięcznie")


async def test_each_scope_has_its_own_goal_and_a_goal_can_be_removed(engine: Engine) -> None:
    save_goal(engine, InvestmentGoal(None, GoalMode.AMOUNT, amount=Decimal(240000)))

    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await user.should_see(marker="goal-progress", content=f"Cel: {_pln('240 000,00')} · 50{NBSP}%")

        await _switch_scope(user, "scope-2")
        await user.should_see(marker="set-goal")
        user.find(marker="set-goal").click()
        await user.should_see(marker="goal-dialog")
        user.find(marker="goal-amount").type("40 000")
        user.find(marker="goal-save").click()
        await user.should_see(marker="goal-progress", content=f"Cel: {_pln('40 000,00')} · 50{NBSP}%")

        await _switch_scope(user, "scope-total")
        await user.should_see(marker="goal-progress", content=_pln("240 000,00"))
        user.find(marker="edit-goal").click()
        await user.should_see(marker="goal-dialog")
        user.find(marker="goal-delete").click()
        await user.should_see(marker="set-goal")

    assert load_goal(engine, None) is None
    assert load_goal(engine, 2) == InvestmentGoal(2, GoalMode.AMOUNT, amount=Decimal(40000))


async def test_a_goal_that_does_not_read_is_not_saved(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        user.find(marker="set-goal").click()
        await user.should_see(marker="goal-dialog")
        user.find(marker="goal-amount").type("milion")
        user.find(marker="goal-save").click()

        await user.should_see(marker="goal-error", content="Kwota celu: wpisz liczbę, np. 1 000 000.")

    assert load_goal(engine, None) is None
