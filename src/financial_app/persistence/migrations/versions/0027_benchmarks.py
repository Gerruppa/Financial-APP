"""Benchmarks (issue #91, spec 6).

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "benchmarks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("offset", sa.String(length=20), nullable=False),
        sa.Column("shown", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_benchmarks_account_id_accounts")),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name=op.f("fk_benchmarks_instrument_id_instruments")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_benchmarks")),
    )


def downgrade() -> None:
    op.drop_table("benchmarks")
