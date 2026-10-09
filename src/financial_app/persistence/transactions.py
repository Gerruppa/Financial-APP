"""Reading, saving, editing and deleting Transactions (spec 3.3)."""

from decimal import Decimal

from sqlalchemy import Engine, select, tuple_
from sqlalchemy.orm import Session

from financial_app.domain.lots import open_positions
from financial_app.domain.transactions import Transaction, TransactionDraft, TransactionError, TransactionType
from financial_app.persistence.models import AccountRow, InstrumentRow, TransactionRow


def list_transactions(engine: Engine) -> list[Transaction]:
    """All Transactions, newest first; same-day ones in reverse entry order."""
    with Session(engine) as session:
        rows = session.scalars(select(TransactionRow).order_by(TransactionRow.date.desc(), TransactionRow.id.desc()))
        return [_to_transaction(row) for row in rows]


def add_transaction(engine: Engine, draft: TransactionDraft) -> Transaction:
    """Save ``draft``; a Sell not covered by the Account's Lots raises InsufficientQuantityError (spec 3.3)."""
    with Session(engine) as session, session.begin():
        _check_references(session, draft)
        _check_coverage(session, draft, replacing=None)
        row = TransactionRow()
        _fill(row, draft)
        session.add(row)
        session.flush()
        return _to_transaction(row)


def update_transaction(engine: Engine, transaction_id: int, draft: TransactionDraft) -> Transaction:
    """Replace the Transaction's fields with ``draft``; it keeps its id and so its place in the same-day order.

    Blocked with InsufficientQuantityError if a Sell, this one or a later one, would lose its cover.
    """
    with Session(engine) as session, session.begin():
        row = _get(session, transaction_id)
        _check_references(session, draft)
        _check_coverage(session, draft, replacing=row)
        _fill(row, draft)
        session.flush()
        return _to_transaction(row)


def delete_transaction(engine: Engine, transaction_id: int) -> None:
    """Delete the Transaction; blocked with InsufficientQuantityError if a later Sell would lose its cover."""
    with Session(engine) as session, session.begin():
        row = _get(session, transaction_id)
        _check_coverage(session, None, replacing=row)
        session.delete(row)


def _get(session: Session, transaction_id: int) -> TransactionRow:
    row = session.get(TransactionRow, transaction_id)
    if row is None:
        raise TransactionError("Ta transakcja nie istnieje.")
    return row


def _check_references(session: Session, draft: TransactionDraft) -> None:
    # SQLite does not enforce foreign keys unless asked to, so check the references here
    if session.get(AccountRow, draft.account_id) is None:
        raise TransactionError("Wybrane konto nie istnieje.")
    if draft.instrument_id is not None:
        instrument = session.get(InstrumentRow, draft.instrument_id)
        if instrument is None:
            raise TransactionError("Wybrany instrument nie istnieje.")
        # Foreign-currency Buys and Sells need NBP rates (issue #15)
        if instrument.quote_currency != "PLN":
            raise TransactionError("Na razie można kupować i sprzedawać tylko instrumenty notowane w PLN.")


def _check_coverage(session: Session, draft: TransactionDraft | None, replacing: TransactionRow | None) -> None:
    """Replay the Positions ``draft`` and ``replacing`` touch, with ``draft`` in place of ``replacing``.

    A new ``draft`` (``replacing`` is None) comes last in entry order; ``draft`` None deletes ``replacing``.
    Replaying the whole Position means a backdated change cannot uncover a later Sell either.
    """
    pairs = {
        (t.account_id, t.instrument_id) for t in (draft, replacing) if t is not None and t.instrument_id is not None
    }
    if not pairs:
        return
    rows = session.scalars(
        select(TransactionRow)
        .where(tuple_(TransactionRow.account_id, TransactionRow.instrument_id).in_(pairs))
        .order_by(TransactionRow.id)
    )
    # The edited Transaction keeps its id, so its draft takes the row's place in entry order
    transactions = [draft if row is replacing else _to_transaction(row) for row in rows]
    if replacing is None:
        transactions.append(draft)
    open_positions(t for t in transactions if t is not None)


def _fill(row: TransactionRow, draft: TransactionDraft) -> None:
    row.account_id = draft.account_id
    row.date = draft.date
    row.transaction_type = draft.transaction_type.value
    row.actual_amount = str(draft.actual_amount)
    row.comment = draft.comment
    row.instrument_id = draft.instrument_id
    row.quantity = _text(draft.quantity)
    row.price = _text(draft.price)
    row.commission = str(draft.commission) if draft.transaction_type.is_buy_or_sell else None


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decimal(text: str | None) -> Decimal | None:
    return None if text is None else Decimal(text)


def _to_transaction(row: TransactionRow) -> Transaction:
    return Transaction(
        id=row.id,
        account_id=row.account_id,
        date=row.date,
        transaction_type=TransactionType(row.transaction_type),
        actual_amount=Decimal(row.actual_amount),
        comment=row.comment,
        instrument_id=row.instrument_id,
        quantity=_decimal(row.quantity),
        price=_decimal(row.price),
        commission=Decimal(row.commission or 0),
    )
