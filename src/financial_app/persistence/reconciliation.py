"""Saving a Reconciliation with a broker's statement (L-17, spec 7): every choice at once, all or none."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import ColumnElement, Engine, or_, select
from sqlalchemy.orm import Session

from financial_app.domain.lots import open_positions
from financial_app.domain.transactions import (
    PLN,
    Origin,
    Transaction,
    TransactionDraft,
    TransactionError,
    TransactionType,
)
from financial_app.persistence.models import InstrumentRow, SkippedBrokerRow, TransactionRow
from financial_app.persistence.transactions import check_references, fill_row, get_row, to_transaction

# What a broker's cash statement can show; the other types (a Split, a Cost, a Currency Exchange, ...) are never
# offered for pairing, so the broker's version cannot delete them
RECONCILED_TYPES = tuple(
    t.value
    for t in (
        TransactionType.DEPOSIT,
        TransactionType.WITHDRAWAL,
        TransactionType.BUY,
        TransactionType.SELL,
        TransactionType.DIVIDEND,
        TransactionType.CASH_TRANSFER,
    )
)


@dataclass(frozen=True)
class AddBroker:
    """A broker-only Transaction, added."""

    draft: TransactionDraft


@dataclass(frozen=True)
class TakeBroker:
    """An entered Transaction replaced by the broker's version of it; it keeps its id, so a Lot it opened keeps its
    name, and its sheet fingerprint, so importing the sheet again still skips it."""

    transaction_id: int
    draft: TransactionDraft


@dataclass(frozen=True)
class KeepMine:
    """An entered Transaction kept as it is: paired with the broker's ``broker_id``, or entered-only (None)."""

    transaction_id: int
    broker_id: str | None = None


@dataclass(frozen=True)
class DeleteMine:
    """An entered-only Transaction removed, as the broker has no such one."""

    transaction_id: int


@dataclass(frozen=True)
class SkipBroker:
    """A broker-only Transaction not added, and not offered again."""

    external_id: str


Action = AddBroker | TakeBroker | KeepMine | DeleteMine | SkipBroker


def handled_broker_ids(engine: Engine) -> set[str]:
    """The broker external ids already resolved: added, paired with an entered Transaction, or skipped."""
    with Session(engine) as session:
        added = session.scalars(select(TransactionRow.external_id).where(TransactionRow.external_id.is_not(None)))
        paired = session.scalars(select(TransactionRow.broker_id).where(TransactionRow.broker_id.is_not(None)))
        skipped = session.scalars(select(SkippedBrokerRow.external_id))
        return {*(i for i in added if i), *(i for i in paired if i), *skipped}


def unreconciled_transactions(engine: Engine, ranges: Mapping[int, tuple[date, date]]) -> list[Transaction]:
    """The Transactions entered on each Account of ``ranges`` within its days (those of the broker's statement) that
    no Reconciliation has resolved yet, of the types the statement can show; a broker's own ones are its version
    already. A Dividend of a foreign-currency Instrument is left out, as the import does not read those (spec 7)."""
    with Session(engine) as session:
        rows = session.scalars(
            select(TransactionRow)
            .outerjoin(InstrumentRow, TransactionRow.instrument_id == InstrumentRow.id)
            .where(
                TransactionRow.account_id.in_(ranges),
                TransactionRow.reconciled_on.is_(None),
                TransactionRow.origin != Origin.BROKER.value,
                TransactionRow.transaction_type.in_(RECONCILED_TYPES),
                or_(
                    TransactionRow.transaction_type != TransactionType.DIVIDEND.value,
                    TransactionRow.instrument_id.is_(None),
                    InstrumentRow.quote_currency == PLN,
                ),
                _not_a_foreign_cash_transfer(),
            )
            .order_by(TransactionRow.date, TransactionRow.id)
        )
        return [to_transaction(row) for row in rows if _within(row.date, ranges[row.account_id])]


def incoming_transfers(engine: Engine, ranges: Mapping[int, tuple[date, date]]) -> list[Transaction]:
    """The Cash Transfers entered into each Account of ``ranges`` from another Account, within its days and not yet
    reconciled: the broker shows them as Deposits."""
    with Session(engine) as session:
        rows = session.scalars(
            select(TransactionRow)
            .where(
                TransactionRow.target_account_id.in_(ranges),
                TransactionRow.account_id.not_in(ranges),
                TransactionRow.reconciled_on.is_(None),
                TransactionRow.transaction_type == TransactionType.CASH_TRANSFER.value,
                TransactionRow.cash_currency == PLN,
            )
            .order_by(TransactionRow.date, TransactionRow.id)
        )
        return [
            to_transaction(row)
            for row in rows
            if row.target_account_id and _within(row.date, ranges[row.target_account_id])
        ]


def _not_a_foreign_cash_transfer() -> ColumnElement[bool]:
    """A Cash Transfer in a foreign currency (#125) is none of the statement's, which moves PLN only (spec 7)."""
    return or_(
        TransactionRow.transaction_type != TransactionType.CASH_TRANSFER.value,
        TransactionRow.cash_currency == PLN,
    )


def _within(day: date, days: tuple[date, date]) -> bool:
    return days[0] <= day <= days[1]


def apply_reconciliation(engine: Engine, actions: Sequence[Action], today: date) -> None:
    """Apply every action, then replay the Positions they touch: a Sell or Security Transfer left uncovered, or a Split
    before the first Buy, raises its error and nothing is saved. Deleting a Buy that a coupon or Sell names is
    blocked with TransactionError."""
    with Session(engine) as session, session.begin():
        instruments: set[int] = set()
        deleted: set[int] = set()
        for action in actions:
            match action:
                case AddBroker(draft):
                    check_references(session, draft)
                    row = TransactionRow()
                    fill_row(row, draft)
                    row.reconciled_on = today
                    session.add(row)
                    _touch(instruments, draft.instrument_id)
                case TakeBroker(transaction_id, draft):
                    check_references(session, draft)
                    row = get_row(session, transaction_id)
                    _touch(instruments, row.instrument_id, draft.instrument_id)
                    fingerprint = row.external_id
                    fill_row(row, draft)
                    row.external_id = fingerprint
                    row.broker_id = draft.external_id
                    row.reconciled_on = today
                case KeepMine(transaction_id, broker_id):
                    row = get_row(session, transaction_id)
                    row.broker_id = broker_id
                    row.reconciled_on = today
                case DeleteMine(transaction_id):
                    row = get_row(session, transaction_id)
                    _touch(instruments, row.instrument_id)
                    deleted.add(transaction_id)
                    session.delete(row)
                case SkipBroker(external_id):
                    session.merge(SkippedBrokerRow(external_id=external_id, skipped_on=today))
        session.flush()
        naming = select(TransactionRow.id).where(TransactionRow.lot_id.in_(deleted)).limit(1)
        if deleted and session.scalar(naming) is not None:
            raise TransactionError("Od usuwanej partii zapisano odsetki albo sprzedaż; usuń je najpierw.")
        if instruments:
            rows = session.scalars(
                select(TransactionRow).where(TransactionRow.instrument_id.in_(instruments)).order_by(TransactionRow.id)
            )
            open_positions(to_transaction(row) for row in rows)


def _touch(instruments: set[int], *ids: int | None) -> None:
    instruments.update(i for i in ids if i is not None)
