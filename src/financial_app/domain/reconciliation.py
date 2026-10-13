"""Reconciliation (spec 7, L-17): pairing a broker's Transactions with those already entered on its Accounts.

A broker Transaction pairs with an entered one of the same Account, type, Instrument, quantity and target Account
within ``DATE_WINDOW`` days; one without an Instrument (a Deposit, Withdrawal, Cash Transfer or interest) also needs
its Actual Amount within ``AMOUNT_TOLERANCE_RATIO``, as the amount is all that tells two of them apart. The closest
date pairs first, then the closest amount. A pair is the ``same`` when the date, the Actual Amount (to the grosz),
price, commission and tax agree.

A Cash Transfer entered between an Account of the broker and another one (e.g. from a bank Account) is what the
broker shows as a Deposit or Withdrawal: they pair as ``linked``, and the entered transfer always stays, as it also
moves the other Account's cash. Entered transfers into the broker's Accounts come in as ``incoming``; unpaired, they
are not the broker's to resolve, so they are never entered-only.

What remains is broker-only or entered-only. Each item is resolved by a ``Choice``: the broker's version, which the
broker being the source of truth for its Accounts makes the default, or the one entered ("keep mine").
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from financial_app.domain.transactions import GROSZ, Transaction, TransactionDraft, TransactionType

DATE_WINDOW = 3
AMOUNT_TOLERANCE_RATIO = Decimal("0.01")


class Choice(StrEnum):
    """How an item is resolved: the broker's version (for an entered-only one: deleting it, as the broker does not
    have it; for a broker-only one: adding it) or the user's (keeping theirs, or not adding the broker's)."""

    BROKER = "broker"
    MINE = "mine"


@dataclass(frozen=True)
class Pair:
    mine: Transaction
    broker: TransactionDraft

    @property
    def same(self) -> bool:
        mine, broker = self.mine, self.broker
        if mine.date != broker.date or abs(mine.actual_amount - broker.actual_amount) > GROSZ:
            return False
        details = ("price", "commission", "withholding_tax")
        return self.linked or all(getattr(mine, name) == getattr(broker, name) for name in details)

    @property
    def linked(self) -> bool:
        """An entered Cash Transfer paired with the broker's Deposit or Withdrawal of it."""
        return self.mine.transaction_type is not self.broker.transaction_type

    @property
    def key(self) -> str:
        return _broker_key(self.broker)


@dataclass(frozen=True)
class Reconciliation:
    pairs: list[Pair]
    broker_only: list[TransactionDraft]
    mine_only: list[Transaction]

    @property
    def same(self) -> list[Pair]:
        return [pair for pair in self.pairs if pair.same]

    @property
    def different(self) -> list[Pair]:
        return [pair for pair in self.pairs if not pair.same]


def reconcile(
    broker: Sequence[TransactionDraft], mine: Sequence[Transaction], incoming: Sequence[Transaction] = ()
) -> Reconciliation:
    """Pair ``broker`` Transactions (each with its external id) with the entered ``mine`` and the ``incoming`` Cash
    Transfers into the broker's Accounts, oldest broker one first."""
    unpaired = [*mine, *incoming]
    pairs = []
    broker_only = []
    for draft in sorted(broker, key=lambda d: d.date):
        candidates = [transaction for transaction in unpaired if _matches(draft, transaction)]
        if not candidates:
            broker_only.append(draft)
            continue
        best = min(
            candidates,
            key=lambda t: (abs((t.date - draft.date).days), abs(t.actual_amount - draft.actual_amount), t.id),
        )
        unpaired.remove(best)
        pairs.append(Pair(best, draft))
    entered_only = [transaction for transaction in unpaired if transaction not in incoming]
    return Reconciliation(pairs, broker_only, sorted(entered_only, key=lambda t: (t.date, t.id)))


def _matches(draft: TransactionDraft, transaction: Transaction) -> bool:
    if abs((draft.date - transaction.date).days) > DATE_WINDOW:
        return False
    if transaction.transaction_type is TransactionType.CASH_TRANSFER and draft.target_account_id is None:
        # The broker's leg of a transfer from or to an Account it does not keep
        if draft.transaction_type is TransactionType.WITHDRAWAL:
            linked = transaction.account_id == draft.account_id
        else:
            linked = draft.transaction_type is TransactionType.DEPOSIT
            linked = linked and transaction.target_account_id == draft.account_id
        return linked and _close(draft.actual_amount, transaction.actual_amount)
    keys = ("account_id", "transaction_type", "instrument_id", "quantity", "target_account_id")
    if any(getattr(draft, key) != getattr(transaction, key) for key in keys):
        return False
    return draft.instrument_id is not None or _close(draft.actual_amount, transaction.actual_amount)


def _close(amount: Decimal, other: Decimal) -> bool:
    return abs(amount - other) <= max(amount, other) * AMOUNT_TOLERANCE_RATIO


def item_key(item: Pair | TransactionDraft | Transaction) -> str:
    """The key a ``Choice`` is kept under: a pair or broker-only item by its broker external id, an entered-only one
    by its id."""
    if isinstance(item, Pair):
        return item.key
    if isinstance(item, Transaction):
        return f"mine-{item.id}"
    return _broker_key(item)


def _broker_key(draft: TransactionDraft) -> str:
    assert draft.external_id is not None
    return draft.external_id
