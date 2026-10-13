"""Polish treasury bonds other than Bond Series are quoted on Catalyst through Bossa, as a price per bond (L-23).

Gives the treasury bond class the Fallback Order Bossa unless the user chose one, and drops the Bossa Quotes of the
Polish bond classes, which were percents of nominal; the next price refresh fetches them as prices per bond.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TREASURY = "Obligacje skarbowe polskie"
BOND_CLASSES = (TREASURY, "Obligacje korporacyjne polskie")


def upgrade() -> None:
    asset_classes = sa.table(
        "asset_classes",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("fallback_order", sa.String),
    )
    instruments = sa.table("instruments", sa.column("id", sa.Integer), sa.column("asset_class_id", sa.Integer))
    quotes = sa.table("quotes", sa.column("instrument_id", sa.Integer), sa.column("source", sa.String))
    op.execute(
        asset_classes.update()
        .where(asset_classes.c.name == TREASURY, asset_classes.c.fallback_order == "")
        .values(fallback_order="bossa")
    )
    bonds = (
        sa.select(instruments.c.id)
        .join(asset_classes, asset_classes.c.id == instruments.c.asset_class_id)
        .where(asset_classes.c.name.in_(BOND_CLASSES))
    )
    op.execute(quotes.delete().where(quotes.c.source == "bossa", quotes.c.instrument_id.in_(bonds)))


def downgrade() -> None:
    asset_classes = sa.table("asset_classes", sa.column("name", sa.String), sa.column("fallback_order", sa.String))
    op.execute(
        asset_classes.update()
        .where(asset_classes.c.name == TREASURY, asset_classes.c.fallback_order == "bossa")
        .values(fallback_order="")
    )
