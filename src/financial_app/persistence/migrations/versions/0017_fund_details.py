"""A fund's TER, Distribution Policy and domicile (issue #42).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("instruments") as batch_op:
        batch_op.add_column(sa.Column("ter_percent", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("distribution_policy", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("domicile", sa.String(length=100), server_default="", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("instruments") as batch_op:
        batch_op.drop_column("domicile")
        batch_op.drop_column("distribution_policy")
        batch_op.drop_column("ter_percent")
