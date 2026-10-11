"""Each Asset Class's own, editable Fallback Order (issue #41).

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The spec 4.1 defaults as of this revision; any other class gets the order of "Inne"
DEFAULTS = {
    "Gotówka": "",
    "Akcje polskie": "bossa,yahoo",
    "Akcje zagraniczne": "yahoo,bossa",
    "Obligacje skarbowe polskie": "",
    "Obligacje skarbowe zagraniczne": "yahoo",
    "Obligacje korporacyjne polskie": "bossa",
    "Obligacje korporacyjne zagraniczne": "yahoo",
    "Metale i surowce": "yahoo",
    "Kryptowaluty": "yahoo",
    "Waluty": "",
}
OTHER = "analizy,bankier,yahoo,bossa"


def upgrade() -> None:
    with op.batch_alter_table("asset_classes") as batch_op:
        batch_op.add_column(sa.Column("fallback_order", sa.String(length=100), server_default="", nullable=False))
    asset_classes = sa.table("asset_classes", sa.column("name", sa.String), sa.column("fallback_order", sa.String))
    op.execute(asset_classes.update().where(asset_classes.c.name.not_in(list(DEFAULTS))).values(fallback_order=OTHER))
    for name, order in DEFAULTS.items():
        op.execute(asset_classes.update().where(asset_classes.c.name == name).values(fallback_order=order))


def downgrade() -> None:
    with op.batch_alter_table("asset_classes") as batch_op:
        batch_op.drop_column("fallback_order")
