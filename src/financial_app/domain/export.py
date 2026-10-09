"""The Transakcje list as rows for export (spec 5, issue #22): every Transaction with its amounts, origin and comment.

Pure: the rows hold the stored values, not the display text, so a file can be read back as numbers and dates. The file
writers live in ``sources/export.py``.
"""

from collections.abc import Mapping, Sequence

from financial_app.domain.instruments import Instrument
from financial_app.domain.transactions import Transaction

COLUMNS = (
    "Nr",
    "Data",
    "Konto",
    "Konto docelowe",
    "Typ",
    "Instrument",
    "Waluta",
    "Ilość",
    "Cena",
    "Prowizja",
    "Kwota rzeczywista (PLN)",
    "Kwota podatkowa (PLN)",
    "Kurs NBP",
    "Pochodzenie",
    "Komentarz",
)


def export_rows(
    transactions: Sequence[Transaction], account_names: Mapping[int, str], instruments: Mapping[int, Instrument]
) -> list[tuple[object, ...]]:
    """One row per Transaction, in ``COLUMNS`` order. Missing values are None; a Transaction without an Instrument is
    in the currency of its cash. The Actual and Tax Amounts are always in PLN."""
    rows: list[tuple[object, ...]] = []
    for t in transactions:
        instrument = instruments[t.instrument_id] if t.instrument_id is not None else None
        rows.append(
            (
                t.id,
                t.date,
                account_names[t.account_id],
                None if t.target_account_id is None else account_names[t.target_account_id],
                t.transaction_type.label,
                None if instrument is None else instrument.name,
                instrument.quote_currency if instrument is not None else t.cash_currency,
                t.quantity,
                t.price,
                t.commission,
                t.actual_amount,
                t.tax_amount,
                None if t.nbp_rate is None else t.nbp_rate.rate,
                t.origin.label,
                t.comment,
            )
        )
    return rows
