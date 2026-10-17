"""Reading and saving Investment Goals (issue #96): at most one per View Scope, Total's with no Account."""

from decimal import Decimal

from sqlalchemy import ColumnElement, Engine, delete, select
from sqlalchemy.orm import Session

from financial_app.domain.investment_goal import GoalMode, InvestmentGoal
from financial_app.persistence.models import InvestmentGoalRow


def load_goal(engine: Engine, account_id: int | None) -> InvestmentGoal | None:
    """The goal of the View Scope ``account_id`` (``None``: Total), if one is set."""
    with Session(engine) as session:
        row = session.scalars(select(InvestmentGoalRow).where(_scope(account_id))).first()
        if row is None:
            return None
        return InvestmentGoal(
            account_id=row.account_id,
            mode=GoalMode(row.mode),
            amount=_decimal(row.amount),
            yearly_expenses=_decimal(row.yearly_expenses),
            withdrawal_rate=Decimal(row.withdrawal_rate),
            target_date=row.target_date,
            real_return=Decimal(row.real_return),
            monthly_deposit=_decimal(row.monthly_deposit),
        )


def save_goal(engine: Engine, goal: InvestmentGoal) -> None:
    """Set ``goal`` as its View Scope's goal, replacing the one it had."""
    with Session(engine) as session, session.begin():
        session.execute(delete(InvestmentGoalRow).where(_scope(goal.account_id)))
        session.add(
            InvestmentGoalRow(
                account_id=goal.account_id,
                mode=goal.mode.value,
                amount=_text(goal.amount),
                yearly_expenses=_text(goal.yearly_expenses),
                withdrawal_rate=str(goal.withdrawal_rate),
                target_date=goal.target_date,
                real_return=str(goal.real_return),
                monthly_deposit=_text(goal.monthly_deposit),
            )
        )


def delete_goal(engine: Engine, account_id: int | None) -> None:
    """Remove the View Scope's goal, if any."""
    with Session(engine) as session, session.begin():
        session.execute(delete(InvestmentGoalRow).where(_scope(account_id)))


def _scope(account_id: int | None) -> ColumnElement[bool]:
    if account_id is None:
        return InvestmentGoalRow.account_id.is_(None)
    return InvestmentGoalRow.account_id == account_id


def _decimal(text: str | None) -> Decimal | None:
    return None if text is None else Decimal(text)


def _text(amount: Decimal | None) -> str | None:
    return None if amount is None else str(amount)
