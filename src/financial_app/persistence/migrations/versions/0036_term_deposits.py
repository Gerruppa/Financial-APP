"""Term Deposits and the interest Transactions linked to their periods (issue #160).

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | Sequence[str] | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "term_deposits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("principal", sa.String(length=30), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("term_count", sa.Integer(), nullable=False),
        sa.Column("term_unit", sa.String(length=10), nullable=False),
        sa.Column("annual_rate", sa.String(length=30), nullable=False),
        sa.Column("capitalization", sa.String(length=20), nullable=False),
        sa.Column("renew", sa.Boolean(), nullable=False),
        sa.Column("closed_on", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_term_deposits_account_id_accounts"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_term_deposits")),
    )
    with op.batch_alter_table("term_deposits", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_term_deposits_account_id"), ["account_id"], unique=False)

    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("term_deposit_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("term_deposit_period", sa.Date(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_transactions_term_deposit_id_term_deposits"),
            "term_deposits",
            ["term_deposit_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_transactions_term_deposit_id_term_deposits"), type_="foreignkey")
        batch_op.drop_column("term_deposit_period")
        batch_op.drop_column("term_deposit_id")

    with op.batch_alter_table("term_deposits", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_term_deposits_account_id"))

    op.drop_table("term_deposits")
