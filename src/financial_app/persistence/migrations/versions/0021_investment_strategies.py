"""Investment Strategies: Total's and each Account's Allocation Targets with tolerance bands, and Instrument
Targets (issue #76).

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_strategies_account_id_accounts")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategies")),
        sa.UniqueConstraint("account_id", name=op.f("uq_strategies_account_id")),
    )
    op.create_table(
        "class_targets",
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("asset_class_id", sa.Integer(), nullable=False),
        sa.Column("percent", sa.String(length=20), nullable=False),
        sa.Column("band", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_class_id"], ["asset_classes.id"], name=op.f("fk_class_targets_asset_class_id_asset_classes")
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["strategies.id"], name=op.f("fk_class_targets_strategy_id_strategies")
        ),
        sa.PrimaryKeyConstraint("strategy_id", "asset_class_id", name=op.f("pk_class_targets")),
    )
    with op.batch_alter_table("class_targets", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_class_targets_asset_class_id"), ["asset_class_id"], unique=False)

    op.create_table(
        "instrument_targets",
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("percent", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name=op.f("fk_instrument_targets_instrument_id_instruments")
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["strategies.id"], name=op.f("fk_instrument_targets_strategy_id_strategies")
        ),
        sa.PrimaryKeyConstraint("strategy_id", "instrument_id", name=op.f("pk_instrument_targets")),
    )
    with op.batch_alter_table("instrument_targets", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_instrument_targets_instrument_id"), ["instrument_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("instrument_targets", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_instrument_targets_instrument_id"))

    op.drop_table("instrument_targets")
    with op.batch_alter_table("class_targets", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_class_targets_asset_class_id"))

    op.drop_table("class_targets")
    op.drop_table("strategies")
