"""Transactions and the Cash Balance they produce (spec 3.3, 3.5). For now: PLN Deposits and Withdrawals."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

GROSZ = Decimal("0.01")


class TransactionError(ValueError):
    """A Transaction field the user must correct; the message is shown in the UI (Polish)."""


class TransactionType(StrEnum):
    """Values are stored in the database, so never rename them."""

    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    TransactionType.DEPOSIT: "Wpłata",
    TransactionType.WITHDRAWAL: "Wypłata",
}


@dataclass(frozen=True)
class TransactionDraft:
    """The user-entered fields of a Transaction, validated on creation. ``actual_amount`` is positive PLN."""

    account_id: int
    date: date
    transaction_type: TransactionType
    actual_amount: Decimal
    comment: str = ""

    def __post_init__(self) -> None:
        if not self.actual_amount > 0:
            raise TransactionError("Kwota musi być większa od zera.")
        if self.actual_amount != self.actual_amount.quantize(GROSZ):
            raise TransactionError("Kwotę podaj z dokładnością do grosza.")
        object.__setattr__(self, "comment", self.comment.strip())

    @property
    def cash_change(self) -> Decimal:
        """How the Transaction moves the Account's PLN Cash Balance."""
        return self.actual_amount if self.transaction_type is TransactionType.DEPOSIT else -self.actual_amount


@dataclass(frozen=True)
class Transaction(TransactionDraft):
    """A saved Transaction."""

    id: int = field(kw_only=True)


def cash_balances(transactions: Iterable[TransactionDraft], on: date | None = None) -> dict[int, Decimal]:
    """PLN Cash Balance per Account id at the end of ``on`` (default: all Transactions).

    A balance may go negative: insufficient cash only warns (spec 3.3), so history can be entered in any order.
    """
    balances: dict[int, Decimal] = {}
    for transaction in transactions:
        if on is None or transaction.date <= on:
            balances[transaction.account_id] = (
                balances.get(transaction.account_id, Decimal(0)) + transaction.cash_change
            )
    return balances


def lowest_cash_balance(transactions: Iterable[TransactionDraft], account_id: int, start: date) -> Decimal:
    """The lowest end-of-day PLN Cash Balance of the Account from ``start`` on.

    Below zero means some Transaction lacks cash, which warns but does not block (spec 3.3).
    """
    own = [t for t in transactions if t.account_id == account_id]
    days = sorted({start} | {t.date for t in own if t.date >= start})
    return min(cash_balances(own, on=day).get(account_id, Decimal(0)) for day in days)
