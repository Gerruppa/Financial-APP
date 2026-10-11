"""The View Scope (spec section 5 and 6.1): the Total or one Account, followed by every tab.

It is remembered as text (``total`` or the Account id), falling back to Total when the Account is gone. The switcher
offers the Accounts by value descending, each with its share of the total and its daily change from History.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import Decimal

from financial_app.domain.accounts import Account
from financial_app.domain.metrics import daily_change
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.transactions import TransactionDraft

TOTAL = "total"


@dataclass(frozen=True)
class ScopeEntry:
    """An Account in the switcher; ``value``, ``share`` (a fraction of the total) and ``daily_change`` are ``None``
    while History loads, and ``share`` also when the total is zero."""

    account_id: int
    name: str
    active: bool
    value: Decimal | None
    share: Decimal | None
    daily_change: Decimal | None


def scope_setting(account_id: int | None) -> str:
    """The text a scope is remembered as: ``total`` or the Account id."""
    return TOTAL if account_id is None else str(account_id)


def parse_scope(text: str | None, account_ids: Collection[int]) -> int | None:
    """The remembered scope's Account id, ``None`` (Total) when it is Total, unreadable or of a deleted Account."""
    if text is None or not text.isdigit():
        return None
    account_id = int(text)
    return account_id if account_id in account_ids else None


def in_scope(transaction: TransactionDraft, account_id: int | None) -> bool:
    """Whether the Transaction belongs to the scope: every one in Total, else those of the Account or moving cash or
    units to it."""
    return account_id is None or account_id in (transaction.account_id, transaction.target_account_id)


def scope_entries(accounts: Sequence[Account], history: Sequence[DayValue] | None) -> list[ScopeEntry]:
    """The Accounts by value descending (then by name) with their value today; by name alone while History loads."""
    by_name = sorted(accounts, key=lambda account: account.name.casefold())
    if history is None:
        return [ScopeEntry(a.id, a.name, a.active, None, None, None) for a in by_name]
    today = history[-1] if history else None
    total = today.total if today else Decimal(0)
    entries = []
    for account in by_name:
        value = today.accounts.get(account.id, Decimal(0)) if today else Decimal(0)
        share = value / total if total else None
        change = daily_change(history, account.id)
        entries.append(ScopeEntry(account.id, account.name, account.active, value, share, change or Decimal(0)))
    return sorted(entries, key=lambda entry: -(entry.value or 0))
