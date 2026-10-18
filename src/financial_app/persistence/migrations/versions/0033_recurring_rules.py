"""Recurring Rules, their skips and the occurrence a Transaction covers (issue #97).

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | Sequence[str] | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recurring_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("transaction_type", sa.String(length=20), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.String(length=30), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("frequency", sa.String(length=20), nullable=False),
        sa.Column("day_of_month", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_recurring_rules_account_id_accounts"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name=op.f("fk_recurring_rules_instrument_id_instruments")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recurring_rules")),
    )
    op.create_index(op.f("ix_recurring_rules_account_id"), "recurring_rules", ["account_id"], unique=False)
    op.create_table(
        "recurring_rule_skips",
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("occurrence_date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["recurring_rules.id"],
            name=op.f("fk_recurring_rule_skips_rule_id_recurring_rules"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("rule_id", "occurrence_date", name=op.f("pk_recurring_rule_skips")),
    )
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(sa.Column("recurring_rule_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("recurring_occurrence", sa.Date(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_transactions_recurring_rule_id_recurring_rules"),
            "recurring_rules",
            ["recurring_rule_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_transactions_recurring_rule_id_recurring_rules"), type_="foreignkey")
        batch_op.drop_column("recurring_occurrence")
        batch_op.drop_column("recurring_rule_id")
    op.drop_table("recurring_rule_skips")
    op.drop_index(op.f("ix_recurring_rules_account_id"), table_name="recurring_rules")
    op.drop_table("recurring_rules")
