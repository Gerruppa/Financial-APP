"""Foreign cash on Transactions: the Cash Currency paid from or into and the Currency Exchange direction (issue #16).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(sa.Column("cash_currency", sa.String(length=3), server_default="PLN", nullable=False))
        batch_op.add_column(sa.Column("to_pln", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_column("to_pln")
        batch_op.drop_column("cash_currency")
