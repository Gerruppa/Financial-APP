"""Reading the Transakcje sheet of the user's Inwestomat copy into Transactions (spec 7, issue #20).

Pure: the file itself is read in ``sources/spreadsheet.py``, the NBP Rates and the saved Accounts and Instruments come
in as arguments. A row becomes a ``TransactionDraft`` whose Actual Amount is the sheet's "Total PLN", the PLN that
really moved, and whose Tax Amount is recomputed at the NBP Rate like any other Transaction.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256

from financial_app.domain.currencies import NbpRate
from financial_app.domain.formatting import format_date, parse_date, parse_number
from financial_app.domain.transactions import (
    PLN,
    Origin,
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
    currency_exchange,
)

# The sheet's own column names (its "Transakcje" tab)
COLUMNS = {
    "account": "Konto",
    "date": "Data",
    "ticker": "Ticker",
    "currency": "Waluta",
    "name": "Nazwa",
    "asset_class": "Klasa aktywów",
    "kind": "Rodzaj transakcji",
    "quantity": "Liczba",
    "price": "Cena",
    "commission": "Prowizje",
    "rate": "Kurs PLN transakcji",
    "total": "Total PLN",
    "comment": "Komentarz",
}

CASH_TICKERS = ("gotówka", "gotowka")
SIMILAR_AMOUNT_TOLERANCE = Decimal("0.01")
# TYP-DDMMRR: the day is not part of the Bond Series, which is TYP, month and year, e.g. EDO-040836 -> EDO0836
_BOND = re.compile(r"([A-Z]{2,4})-(\d{2})(\d{2})(\d{2})")
_FOREIGN_CASH = re.compile(r"Waluty_([A-Z]{3})")


class SheetError(TransactionError):
    """A sheet row the import cannot use; the message is shown in the preview (Polish)."""


class SheetKind(StrEnum):
    """The sheet's "Rodzaj transakcji", as far as the import supports it."""

    BUY = "buy"
    SELL = "sell"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"

    @classmethod
    def from_sheet(cls, text: str) -> SheetKind:
        for kind, label in _SHEET_KIND_LABELS.items():
            if text.strip().casefold() == label.casefold():
                return kind
        raise SheetError(f"Nieobsługiwany rodzaj transakcji: „{text.strip()}”.")


_SHEET_KIND_LABELS = {
    SheetKind.BUY: "Zakup",
    SheetKind.SELL: "Sprzedaż",
    SheetKind.DEPOSIT: "Wpłata środków",
    SheetKind.WITHDRAWAL: "Wypłata środków",
}


class TickerKind(StrEnum):
    INSTRUMENT = "instrument"  # EXCH:SYM, a bare Biznesradar code or any other ticker: named by its symbol
    BOND = "bond"  # TYP-DDMMRR: a Bond Series
    CASH = "cash"  # Gotówka: the Account's PLN cash
    FOREIGN_CASH = "foreign_cash"  # Waluty_<CUR>: a foreign Cash Currency


@dataclass(frozen=True)
class Ticker:
    """What a sheet ticker stands for. ``name`` is the Instrument's name, or the currency of foreign cash."""

    kind: TickerKind
    name: str

    @property
    def needs_instrument(self) -> bool:
        return self.kind in (TickerKind.INSTRUMENT, TickerKind.BOND)


def classify_ticker(ticker: str) -> Ticker:
    text = ticker.strip()
    if text.casefold() in CASH_TICKERS:
        return Ticker(TickerKind.CASH, PLN)
    if match := _FOREIGN_CASH.fullmatch(text):
        return Ticker(TickerKind.FOREIGN_CASH, match[1])
    if match := _BOND.fullmatch(text):
        return Ticker(TickerKind.BOND, f"{match[1]}{match[3]}{match[4]}")
    # EXCH:SYM and a bare Biznesradar code (e.g. PKO) both name the Instrument by its bare symbol
    return Ticker(TickerKind.INSTRUMENT, text.rpartition(":")[2])


@dataclass(frozen=True)
class SheetLine:
    """One row of the Transakcje sheet, with its numbers read as decimals."""

    row: int
    account: str
    day: date
    ticker: str
    currency: str
    name: str
    asset_class: str
    kind: str
    quantity: Decimal | None
    price: Decimal | None
    commission: Decimal
    rate: Decimal
    total: Decimal
    comment: str


def parse_lines(header: Sequence[object], rows: Iterable[Sequence[object]]) -> list[SheetLine]:
    """The lines of a sheet whose first row is ``header``; blank rows are skipped.

    Raises SheetError naming the missing columns, so a sheet of another layout is refused rather than misread.
    """
    names = [str(cell or "").strip() for cell in header]
    missing = [label for label in COLUMNS.values() if label not in names]
    if missing:
        raise SheetError(f"W arkuszu brakuje kolumn: {', '.join(missing)}.")
    position = {key: names.index(label) for key, label in COLUMNS.items()}
    lines = []
    for number, row in enumerate(rows, start=2):
        cells = {key: row[index] if index < len(row) else None for key, index in position.items()}
        if all(_text(cell) == "" for cell in cells.values()):
            continue
        lines.append(_line(number, cells))
    return lines


def _line(number: int, cells: dict[str, object]) -> SheetLine:
    try:
        return SheetLine(
            row=number,
            account=_text(cells["account"]),
            day=_date(cells["date"]),
            ticker=_text(cells["ticker"]),
            currency=_text(cells["currency"]).upper() or PLN,
            name=_text(cells["name"]),
            asset_class=_text(cells["asset_class"]),
            kind=_text(cells["kind"]),
            quantity=_number(cells["quantity"]),
            price=_number(cells["price"]),
            commission=_number(cells["commission"]) or Decimal(0),
            rate=_number(cells["rate"]) or Decimal(1),
            total=_number(cells["total"]) or Decimal(0),
            comment=_text(cells["comment"]),
        )
    except (ValueError, TypeError) as error:
        raise SheetError(f"Wiersz {number}: nieprawidłowa wartość ({error}).") from None


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _number(value: object) -> Decimal | None:
    if value is None or _text(value) == "":
        return None
    if isinstance(value, bool):
        raise TypeError("wartość logiczna zamiast liczby")
    if isinstance(value, float | int):
        return Decimal(str(value))
    return parse_number(_text(value))


def _date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return parse_date(_text(value))


def fingerprints(lines: Sequence[SheetLine]) -> list[str]:
    """A stable id per row, so importing the file again recognises the rows already saved.

    It depends on the identity of the row only (Account, date, ticker, kind, quantity, price), so editing its Total PLN
    or comment in the sheet does not make it a new row, and rows added above it keep theirs. Rows with the same identity
    get a running count, so two equal Buys on one day remain two Transactions.
    """
    seen: dict[str, int] = {}
    ids = []
    for line in lines:
        basis = "\x1f".join(
            [
                line.account,
                line.day.isoformat(),
                line.ticker,
                line.kind,
                str(line.quantity),
                str(line.price),
            ]
        )
        count = seen.get(basis, 0)
        seen[basis] = count + 1
        ids.append("sheet-" + sha256(f"{basis}\x1f{count}".encode()).hexdigest())
    return ids


def sheet_draft(
    line: SheetLine,
    *,
    account_id: int,
    instrument_id: int | None,
    nbp_rate: NbpRate | None,
    external_id: str,
) -> TransactionDraft:
    """The Transaction a sheet row becomes, with the Origin "import z arkusza" and the row's fingerprint.

    ``instrument_id`` is the Instrument the row's ticker resolved to. A foreign-currency Instrument needs ``nbp_rate``
    for its Tax Amount, and its sheet rate ("Kurs PLN transakcji") becomes the rate its Actual Amount was taken at.
    """
    kind = SheetKind.from_sheet(line.kind)
    ticker = classify_ticker(line.ticker)
    draft = _draft(line, kind, ticker, account_id, instrument_id, nbp_rate)
    return replace(draft, origin=Origin.SPREADSHEET, external_id=external_id)


def _draft(
    line: SheetLine,
    kind: SheetKind,
    ticker: Ticker,
    account_id: int,
    instrument_id: int | None,
    nbp_rate: NbpRate | None,
) -> TransactionDraft:
    if kind in (SheetKind.DEPOSIT, SheetKind.WITHDRAWAL):
        if ticker.kind is not TickerKind.CASH or line.currency != PLN:
            raise SheetError("Wpłata i wypłata dotyczą tylko gotówki w PLN.")
        transaction_type = TransactionType.DEPOSIT if kind is SheetKind.DEPOSIT else TransactionType.WITHDRAWAL
        return TransactionDraft(account_id, line.day, transaction_type, line.total, line.comment)
    if line.quantity is None:
        raise SheetError(f"Brak liczby w wierszu dla „{line.ticker}”.")
    if ticker.kind is TickerKind.FOREIGN_CASH:
        pln_amount = (line.quantity * line.rate).quantize(Decimal("0.01"))
        return currency_exchange(
            account_id,
            line.day,
            ticker.name,
            line.quantity,
            pln_amount,
            to_pln=kind is SheetKind.SELL,
            comment=line.comment,
        )
    if instrument_id is None:
        raise SheetError(f"Wybierz instrument dla „{line.ticker}”.")
    if line.price is None:
        raise SheetError(f"Brak ceny w wierszu dla „{line.ticker}”.")
    fx_rate = None
    if line.currency != PLN:
        if nbp_rate is None or nbp_rate.currency != line.currency:
            raise SheetError(f"Brak kursu NBP {line.currency} dla {format_date(line.day)}.")
        fx_rate = line.rate if line.rate != 1 else None
    else:
        nbp_rate = None
    # The Actual Amount is calculated as for any Buy or Sell, not taken from the sheet's Total PLN
    transaction_type = TransactionType.BUY if kind is SheetKind.BUY else TransactionType.SELL
    return buy_or_sell(
        account_id,
        line.day,
        transaction_type,
        instrument_id,
        line.quantity,
        line.price,
        line.commission,
        line.comment,
        fx_rate=fx_rate,
        nbp_rate=nbp_rate,
    )


def similar(draft: TransactionDraft, manual: TransactionDraft) -> bool:
    """Whether a sheet row and a Transaction entered by hand are probably the same one (spec 7): the same Account,
    date, type, Instrument and quantity, with the Actual Amounts within 1%."""
    if (draft.account_id, draft.date, draft.transaction_type, draft.instrument_id, draft.quantity) != (
        manual.account_id,
        manual.date,
        manual.transaction_type,
        manual.instrument_id,
        manual.quantity,
    ):
        return False
    larger = max(draft.actual_amount, manual.actual_amount)
    return abs(draft.actual_amount - manual.actual_amount) <= larger * SIMILAR_AMOUNT_TOLERANCE
