"""Mark the Multi-asset class, so that renaming it keeps its Multi-asset Splits on offer (issue #75).

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("asset_classes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("multi_asset", sa.Boolean(), server_default=sa.false(), nullable=False))
    # The seeded class, by the name it had; one renamed before this revision is not found and stays unmarked
    op.execute("UPDATE asset_classes SET multi_asset = 1 WHERE name = 'Multi-asset'")


def downgrade() -> None:
    with op.batch_alter_table("asset_classes", schema=None) as batch_op:
        batch_op.drop_column("multi_asset")
