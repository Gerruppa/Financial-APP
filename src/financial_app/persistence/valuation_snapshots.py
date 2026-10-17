"""Reading and saving Valuation Snapshots (issue #115, ADR-0008): Total's and each Account's figures, at most one a
calendar day, every day kept."""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from financial_app.domain.valuation_snapshots import Figures, ValuationSnapshot
from financial_app.persistence.models import ValuationSnapshotRow


def save_snapshot(engine: Engine, taken_at: datetime, figures: Mapping[int | None, Figures]) -> None:
    """Save the ``figures`` by View Scope (``None`` for Total) taken at ``taken_at``, replacing that day's snapshot."""
    with Session(engine) as session, session.begin():
        session.execute(delete(ValuationSnapshotRow).where(ValuationSnapshotRow.taken_on == taken_at.date()))
        session.add_all(
            ValuationSnapshotRow(
                taken_on=taken_at.date(),
                taken_at=taken_at,
                account_id=account_id,
                value=str(scope.value),
                net_deposits=str(scope.net_deposits),
            )
            for account_id, scope in figures.items()
        )


def snapshot_before(engine: Engine, day: date, account_id: int | None) -> ValuationSnapshot | None:
    """The newest snapshot of the View Scope ``account_id`` (``None``: Total) taken before ``day``, if any."""
    scope = (
        ValuationSnapshotRow.account_id.is_(None)
        if account_id is None
        else ValuationSnapshotRow.account_id == account_id
    )
    with Session(engine) as session:
        row = session.scalars(
            select(ValuationSnapshotRow)
            .where(scope, ValuationSnapshotRow.taken_on < day)
            .order_by(ValuationSnapshotRow.taken_on.desc())
            .limit(1)
        ).first()
        if row is None:
            return None
        return ValuationSnapshot(row.taken_at, Figures(Decimal(row.value), Decimal(row.net_deposits)))
