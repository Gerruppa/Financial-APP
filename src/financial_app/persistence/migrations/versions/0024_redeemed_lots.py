"""The Lot an Early Redemption names (L-5, ADR-0007).

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(sa.Column("lot_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_transactions_lot_id_transactions"), "transactions", ["lot_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_transactions_lot_id_transactions"), type_="foreignkey")
        batch_op.drop_column("lot_id")
