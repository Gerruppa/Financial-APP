"""Reconciliation with a broker's statement (L-17, spec 7).

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(sa.Column("broker_id", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("reconciled_on", sa.Date(), nullable=True))
        batch_op.create_unique_constraint(batch_op.f("uq_transactions_broker_id"), ["broker_id"])
    op.create_table(
        "skipped_broker_rows",
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.Column("skipped_on", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("external_id", name=op.f("pk_skipped_broker_rows")),
    )


def downgrade() -> None:
    op.drop_table("skipped_broker_rows")
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_constraint(batch_op.f("uq_transactions_broker_id"), type_="unique")
        batch_op.drop_column("reconciled_on")
        batch_op.drop_column("broker_id")
