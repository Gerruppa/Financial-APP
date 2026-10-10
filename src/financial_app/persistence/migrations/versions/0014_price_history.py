"""Price history from Stooq and NBP Rate history in the local cache, with the days fetched (issue #33).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "nbp_history",
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("first_day", sa.Date(), nullable=False),
        sa.Column("last_day", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("currency", name=op.f("pk_nbp_history")),
    )
    op.create_table(
        "nbp_rate_history",
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("rate", sa.String(length=30), nullable=False),
        sa.Column("table", sa.String(length=30), nullable=False),
        sa.PrimaryKeyConstraint("currency", "day", name=op.f("pk_nbp_rate_history")),
    )
    op.create_table(
        "quote_history",
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("first_day", sa.Date(), nullable=False),
        sa.Column("last_day", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name=op.f("fk_quote_history_instrument_id_instruments")
        ),
        sa.PrimaryKeyConstraint("instrument_id", name=op.f("pk_quote_history")),
    )


def downgrade() -> None:
    op.drop_table("quote_history")
    op.drop_table("nbp_rate_history")
    op.drop_table("nbp_history")
