"""The target Account of a Cash Transfer Recurring Rule (issue #147).

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | Sequence[str] | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("recurring_rules", schema=None) as batch_op:
        batch_op.add_column(sa.Column("target_account_id", sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f("ix_recurring_rules_target_account_id"), ["target_account_id"], unique=False)
        batch_op.create_foreign_key(
            batch_op.f("fk_recurring_rules_target_account_id_accounts"),
            "accounts",
            ["target_account_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("recurring_rules", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_recurring_rules_target_account_id_accounts"), type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_recurring_rules_target_account_id"))
        batch_op.drop_column("target_account_id")
