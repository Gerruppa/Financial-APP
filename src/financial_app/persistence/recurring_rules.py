"""Recurring Rules, their skipped occurrences and their Drafts (issue #97, spec 3.3.1): the Drafts are computed from
the rules, skips and saved Transactions, and confirmed as ordinary Transactions."""

from datetime import date
from decimal import Decimal

from sqlalchemy import Engine, delete, or_, select, update
from sqlalchemy.orm import Session

from financial_app.domain.bonds import bond_type_of
from financial_app.domain.recurring import (
    Frequency,
    RecurringDraft,
    RecurringRule,
    RecurringRuleDraft,
    RecurringRuleError,
    recurring_drafts,
)
from financial_app.domain.transaction_form import RateLookup
from financial_app.domain.transactions import PLN, Transaction, TransactionType
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.models import (
    AccountRow,
    InstrumentRow,
    RecurringRuleRow,
    RecurringRuleSkipRow,
    TransactionRow,
)
from financial_app.persistence.transactions import add_transaction, transactions_in_entry_order


def list_rules(engine: Engine) -> list[RecurringRule]:
    """Every Recurring Rule, by name."""
    with Session(engine) as session:
        rows = session.scalars(select(RecurringRuleRow).order_by(RecurringRuleRow.name, RecurringRuleRow.id))
        return [_to_rule(row) for row in rows]


def add_rule(engine: Engine, draft: RecurringRuleDraft) -> RecurringRule:
    with Session(engine) as session, session.begin():
        _check_references(session, draft)
        row = RecurringRuleRow()
        _fill(row, draft)
        session.add(row)
        session.flush()
        return _to_rule(row)


def update_rule(engine: Engine, rule_id: int, draft: RecurringRuleDraft) -> RecurringRule:
    """Replace the rule's fields; the Transactions it linked and its skips stay."""
    with Session(engine) as session, session.begin():
        row = _get_row(session, rule_id)
        _check_references(session, draft)
        _fill(row, draft)
        session.flush()
        return _to_rule(row)


def set_rule_active(engine: Engine, rule_id: int, active: bool) -> None:
    """Switch the rule on or off; one switched off gives no Drafts, its Transactions stay."""
    with Session(engine) as session, session.begin():
        _get_row(session, rule_id).active = active


def delete_rule(engine: Engine, rule_id: int) -> None:
    """Delete the rule with its skips; its Transactions stay, no longer linked to it."""
    with Session(engine) as session, session.begin():
        _delete_rules(session, [rule_id])


def delete_rules_of_account(session: Session, account_id: int) -> None:
    """Delete an Account's rules, also the Cash Transfers to it, with their skips, in the Account's own deletion."""
    rule_ids = list(
        session.scalars(
            select(RecurringRuleRow.id).where(
                or_(RecurringRuleRow.account_id == account_id, RecurringRuleRow.target_account_id == account_id)
            )
        )
    )
    _delete_rules(session, rule_ids)


def _delete_rules(session: Session, rule_ids: list[int]) -> None:
    # SQLite runs without foreign keys enforced, so ON DELETE SET NULL and CASCADE alone would leave them
    session.execute(
        update(TransactionRow)
        .where(TransactionRow.recurring_rule_id.in_(rule_ids))
        .values(recurring_rule_id=None, recurring_occurrence=None)
    )
    session.execute(delete(RecurringRuleSkipRow).where(RecurringRuleSkipRow.rule_id.in_(rule_ids)))
    session.execute(delete(RecurringRuleRow).where(RecurringRuleRow.id.in_(rule_ids)))


def skip_occurrence(engine: Engine, rule_id: int, day: date) -> None:
    """Skip the rule's occurrence on ``day`` for good, unless restored; skipping it again changes nothing."""
    with Session(engine) as session, session.begin():
        _get_row(session, rule_id)
        if session.get(RecurringRuleSkipRow, (rule_id, day)) is None:
            session.add(RecurringRuleSkipRow(rule_id=rule_id, occurrence_date=day))


def restore_occurrence(engine: Engine, rule_id: int, day: date) -> None:
    """Undo a skip: the occurrence is a Draft again unless a Transaction covers it."""
    with Session(engine) as session, session.begin():
        session.execute(
            delete(RecurringRuleSkipRow).where(
                RecurringRuleSkipRow.rule_id == rule_id, RecurringRuleSkipRow.occurrence_date == day
            )
        )


def skipped_occurrences(engine: Engine, rule_id: int) -> list[date]:
    """The rule's skipped occurrences, oldest first."""
    with Session(engine) as session:
        return list(
            session.scalars(
                select(RecurringRuleSkipRow.occurrence_date)
                .where(RecurringRuleSkipRow.rule_id == rule_id)
                .order_by(RecurringRuleSkipRow.occurrence_date)
            )
        )


def skip_overdue(engine: Engine, rule_id: int, today: date) -> int:
    """ "Pomiń zaległe": skip each of the rule's Drafts due before ``today``; returns how many."""
    overdue = [d.due for d in pending_recurring_drafts(engine, today) if d.rule.id == rule_id and d.due < today]
    with Session(engine) as session, session.begin():
        session.add_all(RecurringRuleSkipRow(rule_id=rule_id, occurrence_date=day) for day in overdue)
    return len(overdue)


def pending_recurring_drafts(engine: Engine, today: date, account_id: int | None = None) -> list[RecurringDraft]:
    """The Drafts due by ``today`` in the View Scope (``account_id``, ``None`` for Total), oldest first."""
    with Session(engine) as session:
        skipped = {(row.rule_id, row.occurrence_date) for row in session.scalars(select(RecurringRuleSkipRow))}
    bond_types = {
        instrument.id: bond_type
        for instrument in list_instruments(engine)
        if instrument.is_bond_series and (bond_type := bond_type_of(instrument.name)) is not None
    }
    return recurring_drafts(
        list_rules(engine), transactions_in_entry_order(engine), skipped, today, account_id, bond_types
    )


def confirm_recurring_draft(engine: Engine, draft: RecurringDraft, rates: RateLookup) -> Transaction:
    """Save a Deposit, Cost or Cash Transfer Draft as it stands: the rule's amount on the occurrence, a foreign one at
    the NBP Rate (D-1) that ``rates`` gives, linked to the occurrence. A Buy Draft goes through the transaction dialog
    instead."""
    currency = draft.rule.currency
    nbp_rate = None if currency == PLN else rates(currency, draft.due)
    return add_transaction(engine, draft.transaction(nbp_rate))


def _check_references(session: Session, draft: RecurringRuleDraft) -> None:
    # SQLite does not enforce foreign keys unless asked to, so check the references here
    account = session.get(AccountRow, draft.account_id)
    if account is None:
        raise RecurringRuleError("Wybrane konto nie istnieje.")
    if draft.currency not in {cash.currency for cash in account.cash_currencies}:
        raise RecurringRuleError(f"Konto {account.name} nie ma waluty rachunku {draft.currency}.")
    if draft.instrument_id is not None and session.get(InstrumentRow, draft.instrument_id) is None:
        raise RecurringRuleError("Wybrany instrument nie istnieje.")
    if draft.transaction_type is TransactionType.CASH_TRANSFER and draft.target_account_id is not None:
        target = session.get(AccountRow, draft.target_account_id)
        if target is None:
            raise RecurringRuleError("Wybrane konto docelowe nie istnieje.")
        if draft.currency not in {cash.currency for cash in target.cash_currencies}:
            raise RecurringRuleError(f"Konto {target.name} nie ma waluty rachunku {draft.currency}.")


def _get_row(session: Session, rule_id: int) -> RecurringRuleRow:
    row = session.get(RecurringRuleRow, rule_id)
    if row is None:
        raise RecurringRuleError("Ta reguła cykliczna nie istnieje.")
    return row


def _fill(row: RecurringRuleRow, draft: RecurringRuleDraft) -> None:
    row.name = draft.name.strip()
    row.account_id = draft.account_id
    row.transaction_type = draft.transaction_type.value
    # A Deposit names no Instrument, whatever the dialog held before its type changed
    row.instrument_id = draft.instrument_id if draft.transaction_type is TransactionType.BUY else None
    row.target_account_id = draft.target_account_id if draft.transaction_type is TransactionType.CASH_TRANSFER else None
    row.amount = str(draft.amount)
    row.currency = draft.currency
    row.frequency = draft.frequency.value
    row.day_of_month = draft.day_of_month
    row.start_date = draft.start_date
    row.end_date = draft.end_date
    row.active = draft.active


def _to_rule(row: RecurringRuleRow) -> RecurringRule:
    return RecurringRule(
        name=row.name,
        account_id=row.account_id,
        transaction_type=TransactionType(row.transaction_type),
        amount=Decimal(row.amount),
        currency=row.currency,
        frequency=Frequency(row.frequency),
        day_of_month=row.day_of_month,
        start_date=row.start_date,
        end_date=row.end_date,
        instrument_id=row.instrument_id,
        active=row.active,
        target_account_id=row.target_account_id,
        id=row.id,
    )
