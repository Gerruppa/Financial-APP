"""Asset Classes, seeded with the sheet's 12, and the Instrument catalog (issue #12).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The sheet's classes in its order (spec 3.2); the user renames or extends them in Ustawienia
SHEET_ASSET_CLASSES = [
    "Gotówka",
    "Akcje polskie",
    "Akcje zagraniczne",
    "Obligacje skarbowe polskie",
    "Obligacje skarbowe zagraniczne",
    "Obligacje korporacyjne polskie",
    "Obligacje korporacyjne zagraniczne",
    "Metale i surowce",
    "Kryptowaluty",
    "Waluty",
    "Inne",
    "Multi-asset",
]


def upgrade() -> None:
    asset_classes = op.create_table(
        "asset_classes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100, collation="NOCASE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_classes")),
        sa.UniqueConstraint("name", name=op.f("uq_asset_classes_name")),
    )
    op.bulk_insert(asset_classes, [{"name": name, "position": i} for i, name in enumerate(SHEET_ASSET_CLASSES)])
    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200, collation="NOCASE"), nullable=False),
        sa.Column("asset_class_id", sa.Integer(), nullable=False),
        sa.Column("quote_currency", sa.String(length=3), nullable=False),
        sa.Column("market", sa.String(length=100), nullable=False),
        sa.Column("manual_price", sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_class_id"], ["asset_classes.id"], name=op.f("fk_instruments_asset_class_id_asset_classes")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instruments")),
        sa.UniqueConstraint("name", name=op.f("uq_instruments_name")),
    )
    op.create_index(op.f("ix_instruments_asset_class_id"), "instruments", ["asset_class_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_instruments_asset_class_id"), table_name="instruments")
    op.drop_table("instruments")
    op.drop_table("asset_classes")
