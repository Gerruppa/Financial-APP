"""Why the last price refresh failed for an Instrument in every Price Source (issue #37).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "price_failures",
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name=op.f("fk_price_failures_instrument_id_instruments")
        ),
        sa.PrimaryKeyConstraint("instrument_id", "source", name=op.f("pk_price_failures")),
    )


def downgrade() -> None:
    op.drop_table("price_failures")
