"""The export rows of the Transakcje list (spec 5, issue #22): every Transaction type, with its amounts and origin."""

from dataclasses import fields
from datetime import date
from decimal import Decimal

from financial_app.domain.currencies import NbpRate
from financial_app.domain.export import COLUMNS, export_rows
from financial_app.domain.instruments import Instrument
from financial_app.domain.transactions import (
    PLN,
    Origin,
    SplitRatio,
    Transaction,
    TransactionDraft,
    TransactionType,
    buy_or_sell,
    currency_exchange,
    dividend,
    split,
)

DAY = date(2026, 3, 7)
ACCOUNTS = {1: "IKE", 2: "IKZE"}
INSTRUMENTS = {
    10: Instrument("ISAC", 1, "USD", id=10, asset_class_name="Akcje"),
    11: Instrument("ETFPZU", 1, PLN, id=11, asset_class_name="Akcje"),
}
USD = NbpRate("USD", Decimal("3.6500"), date(2026, 3, 6), "045/A/NBP/2026")


def saved(draft: TransactionDraft, transaction_id: int) -> Transaction:
    """The Transaction the database would hold for ``draft``."""
    values = {f.name: getattr(draft, f.name) for f in fields(TransactionDraft)}
    return Transaction(**values, id=transaction_id)


def _row(transactions: list[Transaction]) -> dict[str, object]:
    rows = export_rows(transactions, ACCOUNTS, INSTRUMENTS)
    assert all(len(row) == len(COLUMNS) for row in rows)
    return dict(zip(COLUMNS, rows[0], strict=True))


def test_columns_name_the_amounts_origin_and_comment() -> None:
    assert {"Kwota rzeczywista (PLN)", "Kwota podatkowa (PLN)", "Pochodzenie", "Komentarz"} <= set(COLUMNS)


def test_a_foreign_buy_exports_its_actual_and_tax_amounts_and_rate() -> None:
    draft = buy_or_sell(
        1, DAY, TransactionType.BUY, 10, Decimal(2), Decimal("100"), Decimal("5"), "ręczny zakup", nbp_rate=USD
    )
    row = _row([saved(draft, 7)])

    assert row["Nr"] == 7
    assert row["Data"] == DAY
    assert row["Konto"] == "IKE"
    assert row["Typ"] == TransactionType.BUY.label
    assert row["Instrument"] == "ISAC"
    assert row["Ilość"] == Decimal(2)
    assert row["Cena"] == Decimal("100")
    assert row["Waluta"] == "USD"
    assert row["Kwota rzeczywista (PLN)"] == draft.actual_amount
    assert row["Kwota podatkowa (PLN)"] == draft.tax_amount
    assert row["Kurs NBP"] == USD.rate
    assert row["Pochodzenie"] == Origin.MANUAL.label
    assert row["Komentarz"] == "ręczny zakup"


def test_every_transaction_type_exports_one_row() -> None:
    drafts = [
        TransactionDraft(1, DAY, TransactionType.DEPOSIT, Decimal("1000")),
        TransactionDraft(1, DAY, TransactionType.WITHDRAWAL, Decimal("100")),
        buy_or_sell(1, DAY, TransactionType.BUY, 11, Decimal(3), Decimal("10")),
        buy_or_sell(1, DAY, TransactionType.SELL, 11, Decimal(1), Decimal("12")),
        dividend(1, DAY, Decimal("50"), instrument_id=11),
        TransactionDraft(1, DAY, TransactionType.COST, Decimal("8"), "opłata"),
        currency_exchange(1, DAY, "USD", Decimal(100), Decimal(365)),
        split(1, DAY, 10, SplitRatio(2, 1)),
    ]
    transactions = [saved(draft, number) for number, draft in enumerate(drafts, start=1)]

    rows = export_rows(transactions, ACCOUNTS, INSTRUMENTS)

    assert [row[COLUMNS.index("Typ")] for row in rows] == [t.transaction_type.label for t in transactions]
    assert [row[COLUMNS.index("Nr")] for row in rows] == list(range(1, len(drafts) + 1))


def test_a_transfer_shows_its_target_account_and_missing_values_are_empty() -> None:
    draft = TransactionDraft(1, DAY, TransactionType.DEPOSIT, Decimal("1000"))
    row = _row([saved(draft, 1)])

    assert row["Konto docelowe"] is None
    assert row["Instrument"] is None
    assert row["Kurs NBP"] is None
    assert row["Pochodzenie"] == Origin.MANUAL.label
    assert row["Komentarz"] == ""
