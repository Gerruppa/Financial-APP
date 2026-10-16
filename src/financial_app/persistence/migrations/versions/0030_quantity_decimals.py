"""The decimal places an Instrument's quantity may have (#120), filled from the Transactions entered so far.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-17
"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CRYPTO_DECIMALS = 8


def upgrade() -> None:
    with op.batch_alter_table("instruments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("quantity_decimals", sa.Integer(), server_default="0", nullable=False))
    connection = op.get_bind()
    # The most decimals any of its quantities uses (2.50 counts as 2.5)
    decimals: dict[int, int] = {}
    quantities = connection.execute(
        sa.text(
            "SELECT instrument_id, quantity FROM transactions WHERE instrument_id IS NOT NULL AND quantity IS NOT NULL"
        )
    )
    for instrument_id, quantity in quantities:
        exponent = Decimal(quantity).normalize().as_tuple().exponent
        used = -exponent if isinstance(exponent, int) and exponent < 0 else 0
        decimals[instrument_id] = max(decimals.get(instrument_id, 0), used)
    for instrument_id, used in decimals.items():
        connection.execute(
            sa.text("UPDATE instruments SET quantity_decimals = :used WHERE id = :id"),
            {"used": min(used, CRYPTO_DECIMALS), "id": instrument_id},
        )
    # The crypto class by the name it was seeded with; one renamed since is not found
    connection.execute(
        sa.text(
            "UPDATE instruments SET quantity_decimals = :crypto WHERE asset_class_id IN"
            " (SELECT id FROM asset_classes WHERE name = 'Kryptowaluty')"
        ),
        {"crypto": CRYPTO_DECIMALS},
    )


def downgrade() -> None:
    with op.batch_alter_table("instruments", schema=None) as batch_op:
        batch_op.drop_column("quantity_decimals")
