"""Contribution Limits (spec 8.1): the most that may be paid in a calendar year into the Accounts of one Account Type
(IKE, IKZE or OIPE) taken together."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.formatting import format_pln, parse_number
from financial_app.domain.transactions import PLN, TransactionDraft, TransactionType

LIMITED_TYPES = (AccountType.IKE, AccountType.IKZE, AccountType.OIPE)

# IKZE's higher limit for the self-employed, shown as a hint beside the year's IKZE limit (MRPiPS, November 2025)
IKZE_SELF_EMPLOYED = {2026: Decimal(16956)}

GROSZ = Decimal("0.01")


class ContributionLimitError(ValueError):
    """A Contribution Limit that cannot be saved; the message is Polish, for the user."""


type Limits = Mapping[int, Mapping[AccountType, Decimal | None]]
"""The Contribution Limit per year and limited Account Type; ``None`` (or a missing year) where none is entered."""


@dataclass(frozen=True)
class LimitBar:
    """One limited Account Type's contributions in ``year`` against its limit (``None`` when none is entered)."""

    account_type: AccountType
    year: int
    paid: Decimal
    limit: Decimal | None

    @property
    def left(self) -> Decimal | None:
        return None if self.limit is None else max(self.limit - self.paid, Decimal(0))

    @property
    def over(self) -> Decimal | None:
        return None if self.limit is None else max(self.paid - self.limit, Decimal(0))

    @property
    def share(self) -> Decimal | None:
        """The part of the limit used, as a fraction: a limit of 0 is unused while nothing is paid, else full."""
        if self.limit is None:
            return None
        if not self.limit:
            return Decimal(1 if self.paid else 0)
        return self.paid / self.limit


def contributions(
    transactions: Iterable[TransactionDraft], accounts: Iterable[Account], year: int
) -> dict[AccountType, Decimal]:
    """The PLN paid in ``year`` into each limited Account Type."""
    paid = {account_type: Decimal(0) for account_type in LIMITED_TYPES}
    return paid | _paid_by_year(transactions, accounts).get(year, {})


def _paid_by_year(
    transactions: Iterable[TransactionDraft], accounts: Iterable[Account]
) -> dict[int, dict[AccountType, Decimal]]:
    """The PLN paid into each limited Account Type, by year, in one pass."""
    types = {account.id: account.account_type for account in accounts}
    paid: dict[int, dict[AccountType, Decimal]] = {}
    for transaction in transactions:
        account_type = contribution_type(transaction, types)
        if account_type is not None:
            year = paid.setdefault(transaction.date.year, {})
            year[account_type] = year.get(account_type, Decimal(0)) + transaction.actual_amount
    return paid


def contribution_type(transaction: TransactionDraft, types: Mapping[int, AccountType]) -> AccountType | None:
    """The limited Account Type whose limit ``transaction`` counts towards, if any: a Deposit into such an Account, or a
    Cash Transfer into one from an Account of another type (moving an IKE to another institution is no contribution)."""
    if transaction.transaction_type is TransactionType.DEPOSIT:
        account_type = types.get(transaction.account_id)
    elif transaction.transaction_type is TransactionType.CASH_TRANSFER and transaction.target_account_id is not None:
        account_type = types.get(transaction.target_account_id)
        if account_type is types.get(transaction.account_id):
            return None
    else:
        return None
    return account_type if account_type in LIMITED_TYPES else None


def limit_bars(
    transactions: Iterable[TransactionDraft],
    accounts: Iterable[Account],
    limits: Limits,
    year: int,
    account_id: int | None,
) -> list[LimitBar]:
    """The bars of ``year`` for the View Scope: in Total, each limited type with an active Account or a contribution
    that year; in an Account's scope, its type's bar (over all Accounts of that type), none for an unlimited type."""
    accounts = list(accounts)
    paid = contributions(transactions, accounts, year)
    if account_id is None:
        active = {account.account_type for account in accounts if account.active}
        shown = [account_type for account_type in LIMITED_TYPES if account_type in active or paid[account_type]]
    else:
        shown = [account.account_type for account in accounts if account.id == account_id]
        shown = [account_type for account_type in shown if account_type in LIMITED_TYPES]
    year_limits = limits.get(year, {})
    return [LimitBar(account_type, year, paid[account_type], year_limits.get(account_type)) for account_type in shown]


def over_limit(
    before: Iterable[TransactionDraft],
    after: Iterable[TransactionDraft],
    accounts: Iterable[Account],
    limits: Limits,
    saved: Iterable[TransactionDraft],
) -> list[LimitBar]:
    """The bars a save leaves over their limit with more paid than ``before`` it, once per type and year, among those
    the ``saved`` Transactions count towards (an edit passes both its old and new form); ``before`` and ``after`` are
    all the Transactions either side of the save. So an edit of a comment, or one lowering an amount, never warns."""
    accounts = list(accounts)
    types = {account.id: account.account_type for account in accounts}
    touched: dict[tuple[int, AccountType], None] = {}
    for transaction in saved:
        account_type = contribution_type(transaction, types)
        if account_type is not None:
            touched[transaction.date.year, account_type] = None
    if not touched:
        return []
    paid_before = _paid_by_year(before, accounts)
    paid_after = _paid_by_year(after, accounts)
    bars = []
    for year, account_type in touched:
        paid = paid_after.get(year, {}).get(account_type, Decimal(0))
        bar = LimitBar(account_type, year, paid, limits.get(year, {}).get(account_type))
        if bar.over and paid > paid_before.get(year, {}).get(account_type, Decimal(0)):
            bars.append(bar)
    return bars


def over_limit_warning(bar: LimitBar) -> str:
    return f"{bar.account_type.label} {bar.year}: przekroczono limit wpłat o {format_pln(bar.over or Decimal(0))}."


@dataclass(frozen=True)
class LimitSplit:
    """A Deposit over its limit split in two (#273): ``within`` brings its type exactly to the limit (``None`` when the
    limit is used up already) and ``remainder`` puts the rest on an Account without a limit."""

    within: TransactionDraft | None
    remainder: TransactionDraft

    @property
    def deposits(self) -> list[TransactionDraft]:
        return [deposit for deposit in (self.within, self.remainder) if deposit is not None]


def split_over_limit(deposit: TransactionDraft, bar: LimitBar, account_id: int) -> LimitSplit | None:
    """The split of a PLN ``deposit`` that goes over what ``bar`` (its type and year without it) leaves, the rest on
    ``account_id``; ``None`` when it fits, there is no limit or it is in a foreign currency."""
    left = bar.left
    if left is None or deposit.actual_amount <= left or deposit.cash_currency != PLN:
        return None
    note = f"ponad limit {bar.account_type.label} {bar.year}"
    comment = f"{deposit.comment} (nadwyżka {note})" if deposit.comment else f"Nadwyżka {note}"
    remainder = replace(deposit, account_id=account_id, actual_amount=deposit.actual_amount - left, comment=comment)
    return LimitSplit(replace(deposit, actual_amount=left) if left else None, remainder)


def remainder_accounts(accounts: Iterable[Account], transactions: Iterable[TransactionDraft]) -> list[Account]:
    """The Accounts the rest of a split may go to: active, holding PLN, without a limit and not PPK; the one deposited
    into last comes first, the others in their own order."""
    eligible = [
        account
        for account in accounts
        if account.active
        and PLN in account.cash_currencies
        and account.account_type not in (*LIMITED_TYPES, AccountType.PPK)
    ]
    last: dict[int, date] = {}
    for transaction in transactions:
        if transaction.transaction_type is TransactionType.DEPOSIT:
            last[transaction.account_id] = max(transaction.date, last.get(transaction.account_id, transaction.date))
    return sorted(eligible, key=lambda account: last.get(account.id or 0, date.min), reverse=True)


def parse_limit(text: str) -> Decimal | None:
    """A limit typed in PLN: ``None`` when left empty; raises ContributionLimitError unless an amount of at least 0."""
    if not text.strip():
        return None
    try:
        amount = parse_number(text)
    except ValueError:
        amount = Decimal(-1)
    if amount < 0:
        raise ContributionLimitError("Limit musi być kwotą w zł, nie mniejszą od zera.")
    if amount != amount.quantize(GROSZ):
        raise ContributionLimitError("Limit podaj z dokładnością do grosza.")
    return amount
