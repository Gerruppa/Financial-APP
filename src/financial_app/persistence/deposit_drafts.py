"""Term Deposit Drafts (issue #160): computed from the deposits and the saved Transactions; an interest Draft is
confirmed as ordinary interest, a maturity by ending or renewing the deposit (``persistence/term_deposits.py``)."""

from datetime import date

from sqlalchemy import Engine

from financial_app.domain.term_deposits import DepositDraft, InterestDraft, deposit_drafts
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.term_deposits import list_deposits
from financial_app.persistence.transactions import add_transaction, transactions_in_entry_order


def pending_deposit_drafts(engine: Engine, day: date, account_id: int | None = None) -> list[DepositDraft]:
    """The Drafts due by ``day`` in the View Scope (``account_id``, ``None`` for Total), the earliest first."""
    transactions = transactions_in_entry_order(engine)
    return deposit_drafts(list_deposits(engine), list_accounts(engine), transactions, day, account_id)


def confirm_interest(engine: Engine, draft: InterestDraft) -> None:
    """Save the period's interest, linked to it."""
    add_transaction(engine, draft.transaction())
