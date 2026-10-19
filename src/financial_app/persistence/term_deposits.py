"""Term Deposits (issue #160): saved, edited, ended, renewed and deleted. Their Drafts are in
``persistence/deposit_drafts.py``."""

from dataclasses import fields, replace
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session

from financial_app.domain.accounts import AccountType
from financial_app.domain.term_deposits import (
    Capitalization,
    DepositMaturityDraft,
    TermDeposit,
    TermDepositDraft,
    TermDepositError,
    TermUnit,
)
from financial_app.domain.transactions import PLN
from financial_app.persistence.models import AccountRow, TermDepositRow, TransactionRow


def list_deposits(engine: Engine) -> list[TermDeposit]:
    """Every Term Deposit, the earliest started first."""
    with Session(engine) as session:
        rows = session.scalars(select(TermDepositRow).order_by(TermDepositRow.start_date, TermDepositRow.id))
        return [_to_deposit(row) for row in rows]


def add_deposit(engine: Engine, draft: TermDepositDraft) -> TermDeposit:
    with Session(engine) as session, session.begin():
        _check_account(session, draft.account_id)
        row = TermDepositRow()
        _fill(row, draft)
        session.add(row)
        session.flush()
        return _to_deposit(row)


def update_deposit(engine: Engine, deposit_id: int, draft: TermDepositDraft) -> TermDeposit:
    """Replace the deposit's fields; the interest linked to it stays."""
    with Session(engine) as session, session.begin():
        row = _get_row(session, deposit_id)
        _check_account(session, draft.account_id)
        _fill(row, draft)
        session.flush()
        return _to_deposit(row)


def close_deposit(engine: Engine, deposit_id: int, day: date) -> None:
    """End the deposit on ``day``: its maturity ("Zakończ"), or an earlier day when it is broken, forfeiting the
    period running then."""
    with Session(engine) as session, session.begin():
        row = _get_row(session, deposit_id)
        _fill(row, replace(_draft_of(row), closed_on=day))


def renew_deposit(engine: Engine, draft: DepositMaturityDraft, annual_rate: Decimal) -> TermDeposit:
    """ "Odnów": end the deposit on its maturity and start the same one there, of its whole capital, at
    ``annual_rate``; both or neither."""
    renewal = draft.renewal(annual_rate)
    with Session(engine) as session, session.begin():
        old = _get_row(session, draft.deposit.id)
        _fill(old, replace(_draft_of(old), closed_on=draft.due))
        row = TermDepositRow()
        _fill(row, renewal)
        session.add(row)
        session.flush()
        return _to_deposit(row)


def delete_deposit(engine: Engine, deposit_id: int) -> None:
    """Delete the deposit; its interest stays, no longer linked to it."""
    with Session(engine) as session, session.begin():
        _delete_deposits(session, [deposit_id])


def delete_deposits_of_account(session: Session, account_id: int) -> None:
    """Delete an Account's deposits in the Account's own deletion."""
    ids = list(session.scalars(select(TermDepositRow.id).where(TermDepositRow.account_id == account_id)))
    _delete_deposits(session, ids)


def _delete_deposits(session: Session, ids: list[int]) -> None:
    # SQLite runs without foreign keys enforced, so ON DELETE SET NULL alone would leave the links
    session.execute(
        update(TransactionRow)
        .where(TransactionRow.term_deposit_id.in_(ids))
        .values(term_deposit_id=None, term_deposit_period=None)
    )
    session.execute(delete(TermDepositRow).where(TermDepositRow.id.in_(ids)))


def _check_account(session: Session, account_id: int) -> None:
    account = session.get(AccountRow, account_id)
    if account is None:
        raise TermDepositError("Wybrane konto już nie istnieje.")
    if account.account_type != AccountType.DEPOSIT:
        raise TermDepositError("Lokatę można założyć tylko na koncie typu Lokata / oszczędności.")
    if PLN not in {cash.currency for cash in account.cash_currencies}:
        raise TermDepositError("Lokata jest w złotych, a to konto nie ma waluty PLN.")


def _get_row(session: Session, deposit_id: int) -> TermDepositRow:
    row = session.get(TermDepositRow, deposit_id)
    if row is None:
        raise TermDepositError("Ta lokata już nie istnieje.")
    return row


def _fill(row: TermDepositRow, draft: TermDepositDraft) -> None:
    row.account_id = draft.account_id
    row.name = draft.name.strip()
    row.principal = str(draft.principal)
    row.start_date = draft.start_date
    row.term_count = draft.term_count
    row.term_unit = draft.term_unit.value
    row.annual_rate = str(draft.annual_rate)
    row.capitalization = draft.capitalization.value
    row.renew = draft.renew
    row.closed_on = draft.closed_on


def _draft_of(row: TermDepositRow) -> TermDepositDraft:
    deposit = _to_deposit(row)
    return TermDepositDraft(**{f.name: getattr(deposit, f.name) for f in fields(TermDepositDraft)})


def _to_deposit(row: TermDepositRow) -> TermDeposit:
    return TermDeposit(
        id=row.id,
        account_id=row.account_id,
        name=row.name,
        principal=Decimal(row.principal),
        start_date=row.start_date,
        term_count=row.term_count,
        term_unit=TermUnit(row.term_unit),
        annual_rate=Decimal(row.annual_rate),
        capitalization=Capitalization(row.capitalization),
        renew=row.renew,
        closed_on=row.closed_on,
    )
