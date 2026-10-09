"""The gross amount and withholding tax of a Dividend or DRIP (issue #18).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(sa.Column("gross", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("withholding_tax", sa.String(length=30), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_column("withholding_tax")
        batch_op.drop_column("gross")
