"""Where a Transaction came from and the fingerprint of its imported row (issue #20).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("origin", sa.String(length=20), server_default="manual", nullable=False))
        batch_op.add_column(sa.Column("external_id", sa.String(length=100), nullable=True))
        batch_op.create_unique_constraint(batch_op.f("uq_transactions_external_id"), ["external_id"])


def downgrade() -> None:
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("uq_transactions_external_id"), type_="unique")
        batch_op.drop_column("external_id")
        batch_op.drop_column("origin")
