"""Source Symbols per Price Source and the Instruments' daily Quotes (issue #30).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quotes",
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("price", sa.String(length=30), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name=op.f("fk_quotes_instrument_id_instruments")
        ),
        sa.PrimaryKeyConstraint("instrument_id", "day", name=op.f("pk_quotes")),
    )
    op.create_table(
        "source_symbols",
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name=op.f("fk_source_symbols_instrument_id_instruments")
        ),
        sa.PrimaryKeyConstraint("instrument_id", "source", name=op.f("pk_source_symbols")),
    )


def downgrade() -> None:
    op.drop_table("source_symbols")
    op.drop_table("quotes")
