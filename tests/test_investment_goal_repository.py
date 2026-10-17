"""Saving Investment Goals (issue #96): one per View Scope, replaced and removed, gone with their Account."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.investment_goal import GoalMode, InvestmentGoal
from financial_app.persistence.accounts import add_account, delete_account
from financial_app.persistence.db import init_db
from financial_app.persistence.investment_goals import delete_goal, load_goal, save_goal


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def test_total_and_each_account_keep_their_own_goal(engine: Engine) -> None:
    account = add_account(engine, AccountDraft("XTB", "XTB", AccountType.IKE, ("PLN",))).id
    total = InvestmentGoal(
        None,
        GoalMode.FIRE,
        yearly_expenses=Decimal("60000.50"),
        withdrawal_rate=Decimal("3.5"),
        target_date=date(2040, 12, 31),
        real_return=Decimal("4.5"),
        monthly_deposit=Decimal(2500),
    )
    ike = InvestmentGoal(account, GoalMode.AMOUNT, amount=Decimal(300000))

    save_goal(engine, total)
    save_goal(engine, ike)

    assert load_goal(engine, None) == total
    assert load_goal(engine, account) == ike


def test_a_saved_goal_replaces_the_scopes_goal_and_can_be_removed(engine: Engine) -> None:
    save_goal(engine, InvestmentGoal(None, GoalMode.AMOUNT, amount=Decimal(100)))
    save_goal(engine, InvestmentGoal(None, GoalMode.AMOUNT, amount=Decimal(200)))

    assert load_goal(engine, None) == InvestmentGoal(None, GoalMode.AMOUNT, amount=Decimal(200))

    delete_goal(engine, None)
    assert load_goal(engine, None) is None


def test_deleting_an_account_deletes_its_goal(engine: Engine) -> None:
    account = add_account(engine, AccountDraft("XTB", "XTB", AccountType.IKE, ("PLN",))).id
    save_goal(engine, InvestmentGoal(account, GoalMode.AMOUNT, amount=Decimal(100)))

    delete_account(engine, account)
    again = add_account(engine, AccountDraft("XTB", "XTB", AccountType.IKE, ("PLN",))).id

    assert load_goal(engine, again) is None
