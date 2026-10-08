"""Accounts and their Cash Currencies (issue #10).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100, collation="NOCASE"), nullable=False),
        sa.Column("broker", sa.String(length=100), nullable=False),
        sa.Column("account_type", sa.String(length=20), nullable=False),
        sa.Column("fx_conversion_fee_percent", sa.String(length=20), nullable=True),
        sa.Column("exclude_fx_result", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.UniqueConstraint("name", name=op.f("uq_accounts_name")),
    )
    op.create_table(
        "account_cash_currencies",
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_account_cash_currencies_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("account_id", "currency", name=op.f("pk_account_cash_currencies")),
    )


def downgrade() -> None:
    op.drop_table("account_cash_currencies")
    op.drop_table("accounts")
