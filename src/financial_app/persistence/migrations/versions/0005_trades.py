"""Buy and Sell fields on Transactions (issue #13).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(sa.Column("instrument_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("quantity", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("price", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("commission", sa.String(length=30), nullable=True))
        batch_op.create_index(batch_op.f("ix_transactions_instrument_id"), ["instrument_id"], unique=False)
        batch_op.create_foreign_key(
            batch_op.f("fk_transactions_instrument_id_instruments"), "instruments", ["instrument_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_transactions_instrument_id_instruments"), type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_transactions_instrument_id"))
        batch_op.drop_column("commission")
        batch_op.drop_column("price")
        batch_op.drop_column("quantity")
        batch_op.drop_column("instrument_id")
