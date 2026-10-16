"""Replace the first default GPW benchmarks, WSE:WIG and WSE:SWIG80TR on Stooq, by Beta ETFs on Yahoo (issue #91).

Their history is only on Stooq, which needs the user's API key. Each of the two Instruments still carrying only its
Stooq symbol and no Transaction goes with its benchmark; forgetting that the defaults were added lets the Benchmarki
tab add the missing ones again (the ETFs), leaving those still listed as they are.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | Sequence[str] | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = {"WSE:WIG": "wig", "WSE:SWIG80TR": "swig80tr"}
_INSTRUMENT_TABLES = (
    "benchmarks",
    "source_symbols",
    "bond_rate_corrections",
    "multi_asset_shares",
    "instrument_targets",
    "quotes",
    "price_failures",
    "quote_history",
)


def upgrade() -> None:
    connection = op.get_bind()
    for name, symbol in _OLD.items():
        found = connection.execute(sa.text("SELECT id FROM instruments WHERE name = :name"), {"name": name}).scalar()
        if found is None:
            continue
        symbols = connection.execute(
            sa.text("SELECT source, symbol FROM source_symbols WHERE instrument_id = :id"), {"id": found}
        ).all()
        used = connection.execute(
            sa.text("SELECT 1 FROM transactions WHERE instrument_id = :id LIMIT 1"), {"id": found}
        ).scalar()
        if used or [tuple(row) for row in symbols] != [("stooq", symbol)]:
            continue
        for table in _INSTRUMENT_TABLES:
            connection.execute(sa.text(f"DELETE FROM {table} WHERE instrument_id = :id"), {"id": found})  # noqa: S608
        connection.execute(sa.text("DELETE FROM instruments WHERE id = :id"), {"id": found})
    connection.execute(sa.text("DELETE FROM app_settings WHERE key = 'benchmarks_seeded'"))


def downgrade() -> None:
    """Nothing to restore: the defaults are added again by the Benchmarki tab."""
