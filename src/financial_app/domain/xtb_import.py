"""Reading an XTB account statement (xStation's account-history XLSX, spec 7, L-17) into Transactions.

Pure: ``sources/xtb.py`` opens the workbook and hands over the rows of its "Cash Operations" sheet, the one listing
every movement of cash with the PLN that moved. Each statement is one XTB account (its number in the sheet's first
row); a statement's rows become ``XtbEntry``s, which ``xtb_draft`` turns into Transactions once the user has matched
its account and tickers.

- A Buy or Sell is a "Stock purchase" or "Stock sell" whose comment gives quantity and price ("OPEN BUY XTB.PL 8 @
  140.18"); an order filled in parts ("15/15.3224") is one cash row per part, merged into one Transaction.
- "Free funds interest" is interest, its "Free funds interest tax" of the same month the tax withheld from it.
- A transfer between two XTB accounts (e.g. into the IKE, "Transfer out/in operation") is a Cash Transfer when both
  statements are imported, else a Withdrawal from the one or a Deposit into the other.
- Anything else is listed as not supported, to be entered by hand.
"""

import re
from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from financial_app.domain.currencies import NbpRate
from financial_app.domain.formatting import format_date
from financial_app.domain.instruments import Instrument
from financial_app.domain.prices import BOSSA, YAHOO
from financial_app.domain.transactions import (
    GROSZ,
    PLN,
    BrokerConversion,
    Origin,
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
    cash_transfer,
    dividend,
)

SHEET_NAME = "Cash Operations"
EXTERNAL_ID_PREFIX = "xtb-"
# The header row of the Cash Operations sheet, as xStation names its columns
COLUMNS = {
    "type": "Type",
    "instrument": "Instrument",
    "ticker": "Ticker",
    "time": "Time",
    "amount": "Amount",
    "id": "ID",
    "comment": "Comment",
    "product": "Product",
    "position": "Position ID",
}
# The two legs of a transfer between XTB accounts are booked a few milliseconds apart
TRANSFER_WINDOW = timedelta(minutes=5)
# An XTB ticker's market suffix and the Yahoo one of the same listing
YAHOO_SUFFIXES = {
    "PL": ".WA",
    "US": "",
    "UK": ".L",
    "DE": ".DE",
    "FR": ".PA",
    "NL": ".AS",
    "ES": ".MC",
    "IT": ".MI",
    "CH": ".SW",
    "DK": ".CO",
    "SE": ".ST",
    "NO": ".OL",
    "FI": ".HE",
    "BE": ".BR",
    "PT": ".LS",
    "CZ": ".PR",
}

_TRADE = re.compile(
    r"(?P<side>OPEN|CLOSE) BUY (?:\S*[A-Za-z]\S* )?(?P<quantity>\d+(?:\.\d+)?)(?:/\d+(?:\.\d+)?)? @ "
    r"(?P<price>\d+(?:\.\d+)?)"
)
_MONTH = re.compile(r"\d{4}-\d{2}")


class XtbError(TransactionError):
    """A statement the import cannot read; the message is shown to the user (Polish)."""


@dataclass(frozen=True)
class CashOperation:
    """One row of the Cash Operations sheet; ``time`` in UTC, ``amount`` the PLN it moved (negative when paid)."""

    kind: str
    instrument: str
    ticker: str
    time: datetime
    amount: Decimal
    id: str
    comment: str
    product: str
    position: str


@dataclass(frozen=True)
class XtbStatement:
    """One XTB account's Cash Operations from ``since`` to ``until`` (UTC), the exported range."""

    account: str
    operations: list[CashOperation]
    until: datetime
    since: datetime = datetime(1970, 1, 1)

    @property
    def product(self) -> str:
        """The account's product as XTB names it ("My Trades", "IKE", "IKZE"), "" without operations."""
        products = [operation.product for operation in self.operations if operation.product]
        return max(set(products), key=products.count) if products else ""

    @property
    def last_day(self) -> date:
        return warsaw_day(self.until)

    @property
    def first_day(self) -> date:
        return warsaw_day(self.since)


class EntryKind(StrEnum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER = "transfer"
    BUY = "buy"
    SELL = "sell"
    INTEREST = "interest"
    DIVIDEND = "dividend"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class XtbEntry:
    """What one or more cash rows of an XTB ``account`` make: ``amount`` is the PLN that moved, always positive (a
    Buy's price paid, a Sell's proceeds, interest's or a Dividend's gross amount, its tax in ``withholding_tax``).
    A transfer names the receiving account in ``target``; an unsupported row says what it is in ``note``."""

    account: str
    kind: EntryKind
    time: datetime
    ids: tuple[str, ...]
    amount: Decimal
    ticker: str = ""
    name: str = ""
    quantity: Decimal | None = None
    price: Decimal | None = None
    withholding_tax: Decimal = Decimal(0)
    target: str | None = None
    note: str = ""

    @property
    def day(self) -> date:
        return warsaw_day(self.time)

    @property
    def external_id(self) -> str:
        """Stable across exports: the cash rows keep their ids, and the lowest of them names the Transaction; a transfer
        is named by both its legs (sent, received), as either may have been imported alone before."""
        if self.kind is EntryKind.TRANSFER:
            return EXTERNAL_ID_PREFIX + "+".join(self.ids)
        return EXTERNAL_ID_PREFIX + min(self.ids, key=int)

    @property
    def needs_instrument(self) -> bool:
        return self.kind in (EntryKind.BUY, EntryKind.SELL, EntryKind.DIVIDEND)


def parse_statement(rows: Iterable[Sequence[object]]) -> XtbStatement:
    """The statement in the rows of a Cash Operations sheet; raises XtbError when it does not look like one."""
    account = ""
    until: datetime | None = None
    since = datetime(1970, 1, 1)
    header: dict[str, int] | None = None
    operations = []
    for row in rows:
        first = _text(row[0]) if row else ""
        if header is None:
            if first == "Account number":
                account = _text(row[1])
            elif first == "Date to (UTC)" and isinstance(row[1], datetime):
                until = row[1]
            elif first == "Date from (UTC)" and isinstance(row[1], datetime):
                since = row[1]
            elif first == COLUMNS["type"]:
                header = {_text(cell): index for index, cell in enumerate(row)}
                missing = [name for name in COLUMNS.values() if name not in header]
                if missing:
                    raise XtbError(f"W zestawieniu XTB brakuje kolumn: {', '.join(missing)}.")
            continue
        if not first or first == "Total":
            continue
        operations.append(_operation({key: row[header[name]] for key, name in COLUMNS.items()}))
    if not account or header is None:
        raise XtbError("To nie jest zestawienie operacji gotówkowych XTB (arkusz „Cash Operations”).")
    if until is None:
        until = max((operation.time for operation in operations), default=datetime(1970, 1, 1))
    return XtbStatement(account, operations, until, since)


def _operation(cells: Mapping[str, object]) -> CashOperation:
    time = cells["time"]
    if not isinstance(time, datetime):
        raise XtbError(f"Operacja XTB {_text(cells['id'])}: brak czasu.")
    try:
        amount = Decimal(str(cells["amount"]))
    except ArithmeticError:
        raise XtbError(f"Operacja XTB {_text(cells['id'])}: nieczytelna kwota.") from None
    return CashOperation(
        kind=_text(cells["type"]),
        instrument=_text(cells["instrument"]),
        ticker=_text(cells["ticker"]),
        time=time,
        amount=amount.quantize(GROSZ),
        id=_text(cells["id"]),
        comment=_text(cells["comment"]),
        product=_text(cells["product"]),
        position=_text(cells["position"]),
    )


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def warsaw_day(moment: datetime) -> date:
    """The day in Poland of a UTC time: summer time (UTC+2) from the last Sunday of March to the last Sunday of
    October, both at 01:00 UTC, else UTC+1."""
    start = _last_sunday(moment.year, 3)
    end = _last_sunday(moment.year, 10)
    offset = 2 if start <= moment.replace(tzinfo=None) < end else 1
    return (moment + timedelta(hours=offset)).date()


def _last_sunday(year: int, month: int) -> datetime:
    last = date(year, month + 1, 1) - timedelta(days=1)
    sunday = last - timedelta(days=(last.weekday() + 1) % 7)
    return datetime(sunday.year, sunday.month, sunday.day, 1)


def xtb_entries(statements: Sequence[XtbStatement]) -> list[XtbEntry]:
    """The entries of the statements imported together, by day: transfers between two of them become one."""
    entries: list[XtbEntry] = []
    legs: list[tuple[XtbStatement, CashOperation]] = []
    for statement in statements:
        trades: dict[tuple[object, ...], list[CashOperation]] = {}
        interest: dict[tuple[str, str], list[CashOperation]] = {}
        dividends: dict[tuple[str, date], list[CashOperation]] = {}
        for operation in statement.operations:
            kind = operation.kind.casefold()
            comment = operation.comment.casefold()
            day = warsaw_day(operation.time)
            if comment.startswith(("transfer in operation", "transfer out operation")):
                legs.append((statement, operation))
            elif kind in ("stock purchase", "stock sell", "stock sale"):
                match = _TRADE.search(operation.comment)
                if match is None:
                    entries.append(_unsupported(statement, operation, "nieczytelny komentarz transakcji"))
                    continue
                key = (kind == "stock purchase", operation.position or operation.id, day, match["price"])
                trades.setdefault(key, []).append(operation)
            elif kind in ("free funds interest", "free funds interest tax"):
                month = _MONTH.search(operation.comment)
                interest.setdefault((month[0] if month else day.isoformat(), kind), []).append(operation)
            elif kind in ("dividend", "divident", "withholding tax"):
                dividends.setdefault((operation.ticker, day), []).append(operation)
            elif kind == "deposit" and operation.amount > 0:
                entries.append(_cash(statement, operation, EntryKind.DEPOSIT))
            elif kind == "withdrawal" and operation.amount < 0:
                entries.append(_cash(statement, operation, EntryKind.WITHDRAWAL))
            else:
                entries.append(_unsupported(statement, operation, "nieobsługiwany rodzaj operacji"))
        entries.extend(_trade(statement, parts) for parts in trades.values())
        entries.extend(_interest(statement, interest))
        entries.extend(_dividends(statement, dividends))
    entries.extend(_transfers(legs))
    return sorted(entries, key=lambda entry: (entry.time, int(min(entry.ids))))


def _cash(statement: XtbStatement, operation: CashOperation, kind: EntryKind, note: str = "") -> XtbEntry:
    return XtbEntry(statement.account, kind, operation.time, (operation.id,), abs(operation.amount), note=note)


def _unsupported(statement: XtbStatement, operation: CashOperation, reason: str) -> XtbEntry:
    return XtbEntry(
        statement.account,
        EntryKind.UNSUPPORTED,
        operation.time,
        (operation.id,),
        abs(operation.amount),
        ticker=operation.ticker,
        name=operation.instrument,
        note=f"{operation.kind} ({operation.comment}): {reason}",
    )


def _trade(statement: XtbStatement, parts: Sequence[CashOperation]) -> XtbEntry:
    """One Buy or Sell from the cash rows of an order filled in parts (the same position, day and price)."""
    first = parts[0]
    matches = [_TRADE.search(part.comment) for part in parts]
    quantity = sum((Decimal(match["quantity"]) for match in matches if match), Decimal(0))
    amount = sum((part.amount for part in parts), Decimal(0))
    buy = first.kind.casefold() == "stock purchase"
    first_match = matches[0]
    assert first_match is not None
    return XtbEntry(
        statement.account,
        EntryKind.BUY if buy else EntryKind.SELL,
        min(part.time for part in parts),
        tuple(part.id for part in parts),
        abs(amount),
        ticker=first.ticker,
        name=first.instrument,
        quantity=quantity,
        price=Decimal(first_match["price"]),
    )


def _interest(statement: XtbStatement, rows: Mapping[tuple[str, str], list[CashOperation]]) -> Iterable[XtbEntry]:
    """Interest on free funds with the tax XTB withheld from it the same month."""
    for (month, kind), paid in rows.items():
        if kind != "free funds interest":
            continue
        taxes = rows.get((month, "free funds interest tax"), [])
        yield XtbEntry(
            statement.account,
            EntryKind.INTEREST,
            min(operation.time for operation in paid),
            tuple(operation.id for operation in [*paid, *taxes]),
            sum((operation.amount for operation in paid), Decimal(0)),
            withholding_tax=-sum((operation.amount for operation in taxes), Decimal(0)),
            note=f"Odsetki od wolnych środków {month}",
        )
    for (month, kind), taxes in rows.items():
        if kind == "free funds interest tax" and (month, "free funds interest") not in rows:
            for operation in taxes:
                yield _unsupported(statement, operation, "podatek bez odsetek z tego miesiąca")


def _dividends(statement: XtbStatement, rows: Mapping[tuple[str, date], list[CashOperation]]) -> Iterable[XtbEntry]:
    """A Dividend with the tax withheld from it, by ticker and day."""
    for (ticker, _), operations in rows.items():
        paid = [operation for operation in operations if operation.kind.casefold() != "withholding tax"]
        taxes = [operation for operation in operations if operation.kind.casefold() == "withholding tax"]
        if not paid:
            for operation in taxes:
                yield _unsupported(statement, operation, "podatek bez dywidendy z tego dnia")
            continue
        yield XtbEntry(
            statement.account,
            EntryKind.DIVIDEND,
            min(operation.time for operation in operations),
            tuple(operation.id for operation in operations),
            sum((operation.amount for operation in paid), Decimal(0)),
            ticker=ticker,
            name=paid[0].instrument,
            withholding_tax=-sum((operation.amount for operation in taxes), Decimal(0)),
        )


def _transfers(legs: Sequence[tuple[XtbStatement, CashOperation]]) -> Iterable[XtbEntry]:
    """A Cash Transfer for each outgoing leg whose incoming leg (the same amount, moments later) is in another
    imported statement; a leg alone moves money out of or into what is imported, so it is a Withdrawal or Deposit."""
    incoming = [(statement, operation) for statement, operation in legs if operation.amount > 0]
    for statement, operation in legs:
        if operation.amount > 0:
            continue
        match = next(
            (
                (other, leg)
                for other, leg in incoming
                if other.account != statement.account
                and leg.amount == -operation.amount
                and abs(leg.time - operation.time) <= TRANSFER_WINDOW
            ),
            None,
        )
        if match is None:
            yield _cash(statement, operation, EntryKind.WITHDRAWAL, note=operation.kind)
            continue
        incoming.remove(match)
        other, leg = match
        yield XtbEntry(
            statement.account,
            EntryKind.TRANSFER,
            operation.time,
            (operation.id, leg.id),
            -operation.amount,
            target=other.account,
            note=operation.kind,
        )
    for statement, operation in incoming:
        yield _cash(statement, operation, EntryKind.DEPOSIT, note=operation.kind)


def unresolved(entry: XtbEntry, resolved: Set[str]) -> XtbEntry | None:
    """What of ``entry`` is still to resolve, given the external ids already resolved: None when all of it is. A
    transfer of which one leg was imported alone before (as a Deposit or Withdrawal) leaves only the other leg, so the
    money is never counted twice."""
    if entry.kind is not EntryKind.TRANSFER:
        return None if entry.external_id in resolved else entry
    sent, received = (EXTERNAL_ID_PREFIX + leg for leg in entry.ids)
    if entry.external_id in resolved or (sent in resolved and received in resolved):
        return None  # sent and received alone: both accounts were imported apart before
    if received in resolved:
        return replace(entry, kind=EntryKind.WITHDRAWAL, ids=entry.ids[:1], target=None)
    if sent in resolved:
        assert entry.target is not None
        return replace(entry, account=entry.target, kind=EntryKind.DEPOSIT, ids=entry.ids[1:], target=None)
    return entry


def yahoo_symbol(ticker: str) -> str:
    """The Yahoo symbol of an XTB ticker ("ISAC.UK" -> "ISAC.L"), or "" for a market it does not know."""
    base, _, market = ticker.rpartition(".")
    if not base or market not in YAHOO_SUFFIXES:
        return ""
    return base + YAHOO_SUFFIXES[market]


def match_instrument(ticker: str, instruments: Iterable[Instrument]) -> Instrument | None:
    """The one Instrument an XTB ticker names: by its Yahoo symbol, its Bossa symbol on GPW, or its name being the
    ticker or the ticker without its market ("ISAC", as the sheet names it); None when none or several do."""
    base, _, market = ticker.rpartition(".")
    base = base or ticker
    yahoo = yahoo_symbol(ticker)
    names = {ticker.casefold(), base.casefold()}
    found = [
        instrument
        for instrument in instruments
        if (yahoo and instrument.source_symbols.get(YAHOO, "").casefold() == yahoo.casefold())
        or (market == "PL" and instrument.source_symbols.get(BOSSA, "").casefold() == base.casefold())
        or instrument.name.casefold() in names
    ]
    return found[0] if len(found) == 1 else None


@dataclass(frozen=True)
class EntryContext:
    """What turns an entry into a Transaction: its Account (``target_account_id`` for a transfer), its Instrument,
    the NBP Rate (D-1) of a foreign Instrument and the Account's FX Conversion Fee %."""

    account_id: int
    target_account_id: int | None = None
    instrument: Instrument | None = None
    nbp_rate: NbpRate | None = None
    fee_percent: Decimal | None = None
    comment: str = ""


def xtb_draft(entry: XtbEntry, context: EntryContext) -> TransactionDraft:
    """The Transaction an entry becomes, with the Origin "import od brokera" and the entry's external id.

    A foreign-currency Buy or Sell is converted by XTB from the PLN Account: the PLN it charged or credited is its
    Actual Amount, at the Account's FX Conversion Fee (0 when none is set). On a PLN one any PLN above quantity ×
    price is its commission.
    """
    draft = _draft(entry, context)
    return replace(draft, origin=Origin.BROKER, external_id=entry.external_id)


def _draft(entry: XtbEntry, context: EntryContext) -> TransactionDraft:
    account_id = context.account_id
    comment = context.comment or entry.note
    match entry.kind:
        case EntryKind.DEPOSIT:
            return TransactionDraft(account_id, entry.day, TransactionType.DEPOSIT, entry.amount, comment)
        case EntryKind.WITHDRAWAL:
            return TransactionDraft(account_id, entry.day, TransactionType.WITHDRAWAL, entry.amount, comment)
        case EntryKind.TRANSFER:
            if context.target_account_id is None:
                raise XtbError("Wybierz konto docelowe przelewu.")
            return cash_transfer(account_id, entry.day, context.target_account_id, entry.amount, comment)
        case EntryKind.INTEREST:
            return dividend(account_id, entry.day, entry.amount, entry.withholding_tax, comment)
        case EntryKind.UNSUPPORTED:
            raise XtbError(f"Operacja nieobsługiwana: {entry.note}.")
    instrument = context.instrument
    if instrument is None:
        raise XtbError(f"Wybierz instrument dla „{entry.ticker}”.")
    if entry.kind is EntryKind.DIVIDEND:
        if instrument.quote_currency != PLN:
            raise XtbError(f"Dywidenda z {entry.ticker} w walucie obcej: wpisz ją ręcznie.")
        return dividend(
            account_id, entry.day, entry.amount, entry.withholding_tax, comment, instrument_id=instrument.id
        )
    assert entry.quantity is not None and entry.price is not None
    transaction_type = TransactionType.BUY if entry.kind is EntryKind.BUY else TransactionType.SELL
    if instrument.quote_currency == PLN:
        value = (entry.quantity * entry.price).quantize(GROSZ)
        difference = entry.amount - value if transaction_type is TransactionType.BUY else value - entry.amount
        return buy_or_sell(
            account_id,
            entry.day,
            transaction_type,
            instrument.id,
            entry.quantity,
            entry.price,
            max(difference, Decimal(0)),
            comment,
        )
    if context.nbp_rate is None:
        raise XtbError(f"Brak kursu NBP {instrument.quote_currency} dla {format_date(entry.day)}.")
    return buy_or_sell(
        account_id,
        entry.day,
        transaction_type,
        instrument.id,
        entry.quantity,
        entry.price,
        comment=comment,
        nbp_rate=context.nbp_rate,
        conversion=BrokerConversion(entry.amount, context.fee_percent or Decimal(0)),
    )
