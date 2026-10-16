"""The bond data of Stage 3: the MF file's Bond Series, GUS CPI, the NBP reference rate and each source's last
fetch (spec 3.4.1).

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bond_data_status",
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("succeeded_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("source", name=op.f("pk_bond_data_status")),
    )
    op.create_table(
        "cpi",
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("year_on_year", sa.String(length=20), nullable=True),
        sa.Column("month_on_month", sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint("year", "month", name=op.f("pk_cpi")),
    )
    op.create_table(
        "mf_bond_series",
        sa.Column("series", sa.String(length=10), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("sale_start", sa.Date(), nullable=False),
        sa.Column("sale_end", sa.Date(), nullable=False),
        sa.Column("issue_price", sa.String(length=20), nullable=False),
        sa.Column("rollover_price", sa.String(length=20), nullable=True),
        sa.Column("margin", sa.String(length=20), nullable=True),
        sa.Column("rates", sa.Text(), nullable=False),
        sa.Column("interest", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("series", name=op.f("pk_mf_bond_series")),
    )
    op.create_table(
        "nbp_reference_rates",
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("rate", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("valid_from", name=op.f("pk_nbp_reference_rates")),
    )


def downgrade() -> None:
    op.drop_table("nbp_reference_rates")
    op.drop_table("mf_bond_series")
    op.drop_table("cpi")
    op.drop_table("bond_data_status")
