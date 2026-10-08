"""Reading and saving Transactions (spec 3.3)."""

from decimal import Decimal

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from financial_app.domain.transactions import Transaction, TransactionDraft, TransactionError, TransactionType
from financial_app.persistence.models import AccountRow, TransactionRow


def list_transactions(engine: Engine) -> list[Transaction]:
    """All Transactions, newest first; same-day ones in reverse entry order."""
    with Session(engine) as session:
        rows = session.scalars(select(TransactionRow).order_by(TransactionRow.date.desc(), TransactionRow.id.desc()))
        return [_to_transaction(row) for row in rows]


def add_transaction(engine: Engine, draft: TransactionDraft) -> Transaction:
    with Session(engine) as session, session.begin():
        # SQLite does not enforce foreign keys unless asked to, so check the Account here
        if session.get(AccountRow, draft.account_id) is None:
            raise TransactionError("Wybrane konto nie istnieje.")
        row = TransactionRow(
            account_id=draft.account_id,
            date=draft.date,
            transaction_type=draft.transaction_type.value,
            actual_amount=str(draft.actual_amount),
            comment=draft.comment,
        )
        session.add(row)
        session.flush()
        return _to_transaction(row)


def _to_transaction(row: TransactionRow) -> Transaction:
    return Transaction(
        id=row.id,
        account_id=row.account_id,
        date=row.date,
        transaction_type=TransactionType(row.transaction_type),
        actual_amount=Decimal(row.actual_amount),
        comment=row.comment,
    )
