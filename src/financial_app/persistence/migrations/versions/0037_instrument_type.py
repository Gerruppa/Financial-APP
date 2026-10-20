"""Instrument Type (issue #198), filled for the Instruments saved so far from what the database knows about them.

A Bond Series in the treasury bond class is Obligacja skarbowa, a metal weight Metal fizyczny, a Fund Code (analizy.pl
or bankier.pl symbol) Fundusz, the crypto class Kryptowaluta, and "ETC"/"ETN" or "ETF" as a word of the name ETC or
ETF; the rest is Inne. No Price Source is asked, so a share is Inne until the user picks Akcja.

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-20
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | Sequence[str] | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# As in domain/bonds.py and domain/prices.py when this was written; a class renamed since is not found
SERIES_NAME = re.compile(r"(OTS|ROR|DOR|TOS|COI|EDO|ROS|ROD)(\d{2})(\d{2})")
TREASURY_BOND_CLASS = "Obligacje skarbowe polskie"
CRYPTO_CLASS = "Kryptowaluty"
FUND_CODE_SOURCES = ("analizy", "bankier")
ETC_WORD = re.compile(r"\bET[CN]\b", re.IGNORECASE)
ETF_WORD = re.compile(r"\bETF\b", re.IGNORECASE)


def _instrument_type(name: str, class_name: str, metal_grams: str | None, fund_code: bool) -> str:
    if class_name == TREASURY_BOND_CLASS and SERIES_NAME.fullmatch(name):
        return "treasury_bond"
    if metal_grams is not None:
        return "metal"
    if fund_code:
        return "fund"
    if class_name == CRYPTO_CLASS:
        return "crypto"
    if ETC_WORD.search(name):
        return "etc"
    if ETF_WORD.search(name):
        return "etf"
    return "other"


def upgrade() -> None:
    with op.batch_alter_table("instruments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("instrument_type", sa.String(length=20), server_default="other", nullable=False))
    connection = op.get_bind()
    with_fund_code = {
        instrument_id
        for (instrument_id,) in connection.execute(
            sa.text("SELECT instrument_id FROM source_symbols WHERE source IN :sources AND symbol != ''").bindparams(
                sa.bindparam("sources", expanding=True)
            ),
            {"sources": list(FUND_CODE_SOURCES)},
        )
    }
    instruments = connection.execute(
        sa.text(
            "SELECT instruments.id, instruments.name, asset_classes.name, instruments.metal_grams FROM instruments"
            " JOIN asset_classes ON asset_classes.id = instruments.asset_class_id"
        )
    )
    for instrument_id, name, class_name, metal_grams in list(instruments):
        kind = _instrument_type(name, class_name, metal_grams, instrument_id in with_fund_code)
        if kind != "other":
            connection.execute(
                sa.text("UPDATE instruments SET instrument_type = :kind WHERE id = :id"),
                {"kind": kind, "id": instrument_id},
            )


def downgrade() -> None:
    with op.batch_alter_table("instruments", schema=None) as batch_op:
        batch_op.drop_column("instrument_type")
