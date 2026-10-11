"""An Instrument's optional ISIN (issue #25).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("instruments") as batch_op:
        batch_op.add_column(sa.Column("isin", sa.String(length=12), server_default="", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("instruments") as batch_op:
        batch_op.drop_column("isin")
