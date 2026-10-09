"""Reading and saving Transactions (spec 3.3)."""

from decimal import Decimal

from sqlalchemy import Engine, select
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
            _check_coverage(session, draft)
        row = TransactionRow(
            account_id=draft.account_id,
            date=draft.date,
            transaction_type=draft.transaction_type.value,
            actual_amount=str(draft.actual_amount),
            comment=draft.comment,
            instrument_id=draft.instrument_id,
            quantity=_text(draft.quantity),
            price=_text(draft.price),
            commission=str(draft.commission) if draft.transaction_type.is_buy_or_sell else None,
        )
        session.add(row)
        session.flush()
        return _to_transaction(row)


def _check_coverage(session: Session, draft: TransactionDraft) -> None:
    """Replay the Position with ``draft`` added, so a backdated Sell cannot uncover a later one either."""
    rows = session.scalars(
        select(TransactionRow)
        .where(TransactionRow.account_id == draft.account_id, TransactionRow.instrument_id == draft.instrument_id)
        .order_by(TransactionRow.id)
    )
    open_positions([*(_to_transaction(row) for row in rows), draft])


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
