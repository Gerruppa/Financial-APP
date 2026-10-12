"""The user's corrections of a Bond Series' MF rates, and automatic valuation of the Bond Series in place of the Manual
Prices the Stage 1 sheet import set (spec 3.4.1).

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-12
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# As domain.bonds has them when this revision was written; a migration never imports the code that changes later
TREASURY_BOND_CLASS = "Obligacje skarbowe polskie"
SERIES_NAME = re.compile(r"(OTS|ROR|DOR|TOS|COI|EDO|ROS|ROD)\d{4}")


def upgrade() -> None:
    op.create_table(
        "bond_rate_corrections",
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("margin", sa.String(length=20), nullable=True),
        sa.Column("rates", sa.Text(), server_default="", nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_bond_rate_corrections_instrument_id_instruments"),
        ),
        sa.PrimaryKeyConstraint("instrument_id", name=op.f("pk_bond_rate_corrections")),
    )
    connection = op.get_bind()
    bonds = connection.execute(
        sa.text(
            "SELECT instruments.id, instruments.name FROM instruments"
            " JOIN asset_classes ON asset_classes.id = instruments.asset_class_id"
            " WHERE asset_classes.name = :name AND instruments.manual_price IS NOT NULL"
        ),
        {"name": TREASURY_BOND_CLASS},
    )
    for instrument_id, name in bonds.all():
        if SERIES_NAME.fullmatch(name):
            connection.execute(
                sa.text("UPDATE instruments SET manual_price = NULL WHERE id = :id"), {"id": instrument_id}
            )


def downgrade() -> None:
    # The cleared Manual Prices are not restored: they were the sheet's prices on the day of the import
    op.drop_table("bond_rate_corrections")
