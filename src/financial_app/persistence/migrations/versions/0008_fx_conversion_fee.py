"""The FX Conversion Fee % of a foreign-currency Buy or Sell the broker converted from PLN (issue #17).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(sa.Column("fx_conversion_fee_percent", sa.String(length=20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_column("fx_conversion_fee_percent")
