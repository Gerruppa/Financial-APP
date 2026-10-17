"""Investment Goals (issue #96).

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | Sequence[str] | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investment_goals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.String(length=30), nullable=True),
        sa.Column("yearly_expenses", sa.String(length=30), nullable=True),
        sa.Column("withdrawal_rate", sa.String(length=20), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("real_return", sa.String(length=20), nullable=False),
        sa.Column("monthly_deposit", sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_investment_goals_account_id_accounts"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_investment_goals")),
    )


def downgrade() -> None:
    op.drop_table("investment_goals")
