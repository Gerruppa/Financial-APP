"""Valuation Snapshots (issue #115, ADR-0008).

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "valuation_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("taken_on", sa.Date(), nullable=False),
        sa.Column("taken_at", sa.DateTime(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("value", sa.String(length=30), nullable=False),
        sa.Column("net_deposits", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_valuation_snapshots_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_valuation_snapshots")),
    )
    with op.batch_alter_table("valuation_snapshots", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_valuation_snapshots_taken_on"), ["taken_on"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("valuation_snapshots", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_valuation_snapshots_taken_on"))
    op.drop_table("valuation_snapshots")
