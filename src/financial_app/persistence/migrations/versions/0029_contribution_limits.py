"""Contribution Limits (issue #95, spec 8.1), 2026 seeded from the MRPiPS notices of November 2025.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | Sequence[str] | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = op.create_table(
        "contribution_limits",
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("account_type", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint("year", "account_type", name=op.f("pk_contribution_limits")),
    )
    op.bulk_insert(
        table,
        [
            {"year": 2026, "account_type": "ike", "amount": "28260"},
            {"year": 2026, "account_type": "ikze", "amount": "11304"},
            {"year": 2026, "account_type": "oipe", "amount": "28260"},
        ],
    )


def downgrade() -> None:
    op.drop_table("contribution_limits")
