"""Contribution Limits (spec 8.1): the most that may be paid in a calendar year into the Accounts of one Account Type
(IKE, IKZE or OIPE) taken together."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.formatting import format_pln, parse_number
from financial_app.domain.transactions import TransactionDraft, TransactionType

LIMITED_TYPES = (AccountType.IKE, AccountType.IKZE, AccountType.OIPE)

# IKZE's higher limit for the self-employed, shown as a hint beside the year's IKZE limit (MRPiPS, November 2025)
IKZE_SELF_EMPLOYED = {2026: Decimal(16956)}


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


def contributions(
    transactions: Iterable[TransactionDraft], accounts: Iterable[Account], year: int
) -> dict[AccountType, Decimal]:
    """The PLN paid in ``year`` into each limited Account Type."""
    types = {account.id: account.account_type for account in accounts}
    paid = {account_type: Decimal(0) for account_type in LIMITED_TYPES}
    for transaction in transactions:
        account_type = contribution_type(transaction, types)
        if account_type is not None and transaction.date.year == year:
            paid[account_type] += transaction.actual_amount
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
    transactions: Iterable[TransactionDraft],
    accounts: Iterable[Account],
    limits: Limits,
    saved: Iterable[TransactionDraft],
) -> list[LimitBar]:
    """The bars over their limit, once per type and year, among those the ``saved`` Transactions count towards;
    ``transactions`` are all of them after the save."""
    accounts = list(accounts)
    types = {account.id: account.account_type for account in accounts}
    touched: dict[tuple[int, AccountType], None] = {}
    for transaction in saved:
        account_type = contribution_type(transaction, types)
        if account_type is not None:
            touched[transaction.date.year, account_type] = None
    transactions = list(transactions)
    bars = []
    for year, account_type in touched:
        paid = contributions(transactions, accounts, year)[account_type]
        bar = LimitBar(account_type, year, paid, limits.get(year, {}).get(account_type))
        if bar.over:
            bars.append(bar)
    return bars


def over_limit_warning(bar: LimitBar) -> str:
    return f"{bar.account_type.label} {bar.year}: przekroczono limit wpłat o {format_pln(bar.over or Decimal(0))}."


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
    return amount
