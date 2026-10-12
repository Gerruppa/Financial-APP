"""Each Instrument's Multi-asset Split, a share per Asset Class (issue #75).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "multi_asset_shares",
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("asset_class_id", sa.Integer(), nullable=False),
        sa.Column("percent", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_class_id"], ["asset_classes.id"], name=op.f("fk_multi_asset_shares_asset_class_id_asset_classes")
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name=op.f("fk_multi_asset_shares_instrument_id_instruments")
        ),
        sa.PrimaryKeyConstraint("instrument_id", "asset_class_id", name=op.f("pk_multi_asset_shares")),
    )
    with op.batch_alter_table("multi_asset_shares", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_multi_asset_shares_asset_class_id"), ["asset_class_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("multi_asset_shares", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_multi_asset_shares_asset_class_id"))
    op.drop_table("multi_asset_shares")
