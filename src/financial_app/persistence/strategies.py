"""Reading and saving Investment Strategies (issue #76): Total's and each Account's own."""

from decimal import Decimal

from sqlalchemy import ColumnElement, Engine, select
from sqlalchemy.orm import Session, selectinload

from financial_app.domain.strategy import ClassTarget, Strategy
from financial_app.persistence.models import ClassTargetRow, InstrumentTargetRow, StrategyRow


def list_strategies(engine: Engine) -> dict[int | None, Strategy]:
    """Every saved Investment Strategy by its Account id, Total's under ``None``."""
    with Session(engine) as session:
        rows = session.scalars(
            select(StrategyRow).options(
                selectinload(StrategyRow.class_targets), selectinload(StrategyRow.instrument_targets)
            )
        )
        return {row.account_id: _to_strategy(row) for row in rows}


def save_strategy(engine: Engine, strategy: Strategy) -> None:
    """Save ``strategy`` in place of the one its Account (or Total) had."""
    with Session(engine) as session, session.begin():
        row = session.scalar(select(StrategyRow).where(_owned_by(strategy.account_id)))
        if row is None:
            row = StrategyRow(account_id=strategy.account_id)
            session.add(row)
        row.class_targets = [
            ClassTargetRow(asset_class_id=class_id, percent=str(target.percent), band=str(target.band))
            for class_id, target in strategy.class_targets.items()
        ]
        row.instrument_targets = [
            InstrumentTargetRow(instrument_id=instrument_id, percent=str(percent))
            for instrument_id, percent in strategy.instrument_targets.items()
        ]


def delete_strategy(engine: Engine, account_id: int | None) -> None:
    """Remove the Account's own Investment Strategy (or Total's), if it has one."""
    with Session(engine) as session, session.begin():
        row = session.scalar(select(StrategyRow).where(_owned_by(account_id)))
        if row is not None:
            session.delete(row)


def _owned_by(account_id: int | None) -> ColumnElement[bool]:
    return StrategyRow.account_id.is_(None) if account_id is None else StrategyRow.account_id == account_id


def _to_strategy(row: StrategyRow) -> Strategy:
    return Strategy(
        row.account_id,
        {t.asset_class_id: ClassTarget(Decimal(t.percent), Decimal(t.band)) for t in row.class_targets},
        {t.instrument_id: Decimal(t.percent) for t in row.instrument_targets},
    )
