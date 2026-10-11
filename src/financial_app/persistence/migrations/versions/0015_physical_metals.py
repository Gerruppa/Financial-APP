"""A physical metal's weight per unit and Buyback Spread % (issue #34).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("instruments") as batch_op:
        batch_op.add_column(sa.Column("metal_grams", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("buyback_spread_percent", sa.String(length=20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("instruments") as batch_op:
        batch_op.drop_column("buyback_spread_percent")
        batch_op.drop_column("metal_grams")
