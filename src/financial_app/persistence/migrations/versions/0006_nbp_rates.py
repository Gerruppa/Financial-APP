"""NBP Rates on foreign-currency Transactions and their local cache (issue #15).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "nbp_rates",
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("rate", sa.String(length=30), nullable=False),
        sa.Column("published_on", sa.Date(), nullable=False),
        sa.Column("table", sa.String(length=30), nullable=False),
        sa.PrimaryKeyConstraint("currency", "day", name=op.f("pk_nbp_rates")),
    )
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(sa.Column("fx_rate", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("nbp_currency", sa.String(length=3), nullable=True))
        batch_op.add_column(sa.Column("nbp_rate", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("nbp_published_on", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("nbp_table", sa.String(length=30), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_column("nbp_table")
        batch_op.drop_column("nbp_published_on")
        batch_op.drop_column("nbp_rate")
        batch_op.drop_column("nbp_currency")
        batch_op.drop_column("fx_rate")
    op.drop_table("nbp_rates")
