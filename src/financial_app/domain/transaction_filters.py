"""Excel-like filters and sorting of the Transakcje list (L-27).

Each column header sorts by its column and filters it: the Account, Transaction Type and Instrument by the values the
list holds, the amount (the Actual Amount, which it also sorts by)
and the date by a range including its ends, and the comment by contained
text ignoring case. The filters combine with the View Scope, which picks the list first; the export takes the same
view.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from financial_app.domain.transactions import Transaction, TransactionType

# The Instrument filter's value for Transactions without an Instrument (cash, Currency Exchanges, interest)
NO_INSTRUMENT = 0


class Column(StrEnum):
    DATE = "date"
    ACCOUNT = "account"
    TYPE = "type"
    INSTRUMENT = "instrument"
    AMOUNT = "amount"
    COMMENT = "comment"


@dataclass(frozen=True)
class Sort:
    """The column the list is sorted by; the default is the date, newest first."""

    column: Column = Column.DATE
    descending: bool = True


@dataclass(frozen=True)
class TransactionFilter:
    """What the list keeps; ``None`` (or a blank comment) leaves a column unfiltered. ``accounts`` matches a Transfer's
    target Account too, ``instruments`` holds ``NO_INSTRUMENT`` for those without one."""

    accounts: frozenset[int] | None = None
    types: frozenset[TransactionType] | None = None
    instruments: frozenset[int] | None = None
    amount_from: Decimal | None = None
    amount_to: Decimal | None = None
    date_from: date | None = None
    date_to: date | None = None
    comment: str = ""

    def is_set(self, column: Column) -> bool:
        """Whether the column's filter is set, shown on its header."""
        match column:
            case Column.DATE:
                return self.date_from is not None or self.date_to is not None
            case Column.ACCOUNT:
                return self.accounts is not None
            case Column.TYPE:
                return self.types is not None
            case Column.INSTRUMENT:
                return self.instruments is not None
            case Column.AMOUNT:
                return self.amount_from is not None or self.amount_to is not None
            case Column.COMMENT:
                return bool(self.comment.strip())

    @property
    def active(self) -> bool:
        return any(self.is_set(column) for column in Column)

    def chosen(self, column: Column) -> frozenset[object] | None:
        """The values a list column (one of ``CHOICE_COLUMNS``) keeps, ``None`` for all."""
        return getattr(self, _CHOICE_FIELDS[column])  # type: ignore[no-any-return]

    def choose(self, column: Column, values: frozenset[Any] | None) -> TransactionFilter:
        changes: dict[str, Any] = {_CHOICE_FIELDS[column]: values}
        return replace(self, **changes)

    def bounds(self, column: Column) -> tuple[Decimal | date | None, Decimal | date | None]:
        """A range column's (the amount's or the date's) "od" and "do"."""
        first, last = _RANGE_FIELDS[column]
        return getattr(self, first), getattr(self, last)

    def bound(self, column: Column, last: bool, value: Decimal | date | None) -> TransactionFilter:
        """The range column's "do" (``last``) or "od" set to ``value``."""
        changes: dict[str, Any] = {_RANGE_FIELDS[column][last]: value}
        return replace(self, **changes)

    def keeps(self, t: Transaction) -> bool:
        if self.accounts is not None and not self.accounts & {t.account_id, t.target_account_id}:
            return False
        if self.types is not None and t.transaction_type not in self.types:
            return False
        if self.instruments is not None and (t.instrument_id or NO_INSTRUMENT) not in self.instruments:
            return False
        if self.is_set(Column.AMOUNT) and not (
            t.transaction_type.has_amount and _within(t.actual_amount, self.amount_from, self.amount_to)
        ):
            return False  # a Split or Security Transfer has no amount to compare
        if not _within(t.date, self.date_from, self.date_to):
            return False
        text = self.comment.strip().casefold()
        return not text or text in t.comment.casefold()


# The columns filtered by a list of the values present, and the fields holding them and the ranges
CHOICE_COLUMNS = (Column.ACCOUNT, Column.TYPE, Column.INSTRUMENT)
_CHOICE_FIELDS = {Column.ACCOUNT: "accounts", Column.TYPE: "types", Column.INSTRUMENT: "instruments"}
_RANGE_FIELDS = {Column.AMOUNT: ("amount_from", "amount_to"), Column.DATE: ("date_from", "date_to")}

NO_FILTER = TransactionFilter()
NEWEST_FIRST = Sort()


def _within[T: (Decimal, date)](value: T, first: T | None, last: T | None) -> bool:
    return (first is None or value >= first) and (last is None or value <= last)


def view(
    transactions: Sequence[Transaction],
    filters: TransactionFilter,
    sort: Sort,
    account_names: Mapping[int, str],
    instrument_names: Mapping[int, str],
) -> list[Transaction]:
    """The Transactions ``filters`` keeps in ``sort``'s order. ``transactions`` come newest first (same-day ones in
    reverse entry order); the date oldest first reverses that, any other column keeps it among equal values."""
    kept = [t for t in transactions if filters.keeps(t)]
    if sort.column is Column.DATE:
        return kept if sort.descending else kept[::-1]
    return sorted(kept, key=_sort_key(sort.column, account_names, instrument_names), reverse=sort.descending)


def _sort_key(
    column: Column, account_names: Mapping[int, str], instrument_names: Mapping[int, str]
) -> Callable[[Transaction], tuple[bool, str] | Decimal | str]:
    match column:
        case Column.ACCOUNT:
            return lambda t: account_names[t.account_id].casefold()
        case Column.TYPE:
            return lambda t: t.transaction_type.label.casefold()
        case Column.INSTRUMENT:
            # Those without an Instrument last
            return lambda t: (
                (False, instrument_names[t.instrument_id].casefold()) if t.instrument_id is not None else (True, "")
            )
        case Column.AMOUNT:
            return lambda t: t.actual_amount
        case _:
            return lambda t: t.comment.casefold()


def account_options(transactions: Sequence[Transaction], account_names: Mapping[int, str]) -> list[tuple[int, str]]:
    """The Accounts the list holds (Transfers' targets included) by name, for the Account filter."""
    ids = {t.account_id for t in transactions} | {t.target_account_id for t in transactions if t.target_account_id}
    return sorted(((i, account_names[i]) for i in ids), key=lambda option: option[1].casefold())


def type_options(transactions: Sequence[Transaction]) -> list[tuple[TransactionType, str]]:
    """The Transaction Types the list holds, in the dialog's order."""
    present = {t.transaction_type for t in transactions}
    return [(kind, kind.label) for kind in TransactionType if kind in present]


def instrument_options(
    transactions: Sequence[Transaction], instrument_names: Mapping[int, str]
) -> list[tuple[int, str | None]]:
    """The Instruments the list holds by name, then ``NO_INSTRUMENT`` (name ``None``) when some have none."""
    ids = {t.instrument_id for t in transactions}
    named = sorted(((i, instrument_names[i]) for i in ids if i is not None), key=lambda option: option[1].casefold())
    return [*named, (NO_INSTRUMENT, None)] if None in ids else list(named)
