"""Recurring Rules and their Drafts (issue #97, spec 3.3.1).

A Recurring Rule falls due on a schedule; each occurrence up to today that no Transaction covers and the user has not
skipped is a Draft to confirm, like a bond's maturity or coupon (``domain/bond_drafts.py``). Drafts are computed,
never stored: only the rules and their skips are.
"""

import calendar
from collections.abc import Collection, Iterable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from financial_app.domain.currencies import NbpRate
from financial_app.domain.transactions import (
    PLN,
    Transaction,
    TransactionDraft,
    TransactionType,
    deposit_or_withdrawal,
)

# The Transaction Types a rule may repeat (spec 3.3.1 point 3)
RECURRING_TYPES = (TransactionType.DEPOSIT, TransactionType.BUY)
# How far from an occurrence a Transaction entered by hand or imported may lie and still cover it
MATCH_WINDOW = timedelta(days=7)
SATURDAY = 5


class RecurringRuleError(ValueError):
    """A rule's fields do not make a rule; the message is for the user, in Polish."""


class Frequency(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMIANNUAL = "semiannual"
    YEARLY = "yearly"

    @property
    def months(self) -> int:
        return {"monthly": 1, "quarterly": 3, "semiannual": 6, "yearly": 12}[self.value]

    @property
    def label(self) -> str:
        return {"monthly": "co miesiąc", "quarterly": "co kwartał", "semiannual": "co pół roku", "yearly": "co rok"}[
            self.value
        ]


@dataclass(frozen=True)
class RecurringRuleDraft:
    """A Recurring Rule's fields, checked on creation: a Deposit of ``amount`` in ``currency`` (one of the Account's
    Cash Currencies, which the repository checks), or a Buy of the Instrument for about ``amount``. It falls due on
    ``day_of_month`` (the month's last day when shorter) every ``frequency`` from the month of ``start_date``, the
    first occurrence, up to ``end_date``; a Saturday or Sunday moves to the next Monday."""

    name: str
    account_id: int
    transaction_type: TransactionType
    amount: Decimal
    currency: str
    frequency: Frequency
    day_of_month: int
    start_date: date
    end_date: date | None = None
    instrument_id: int | None = None
    active: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise RecurringRuleError("Podaj nazwę reguły.")
        if self.transaction_type not in RECURRING_TYPES:
            raise RecurringRuleError("Reguła cykliczna może być tylko wpłatą albo kupnem.")
        if not self.amount > 0:
            raise RecurringRuleError("Kwota musi być większa od zera.")
        if not 1 <= self.day_of_month <= 31:
            raise RecurringRuleError("Dzień miesiąca musi być od 1 do 31.")
        if self.transaction_type is TransactionType.BUY and self.instrument_id is None:
            raise RecurringRuleError("Wybierz instrument.")
        if self.end_date is not None and self.end_date < self.start_date:
            raise RecurringRuleError("Data końca nie może być przed datą początku.")


@dataclass(frozen=True)
class RecurringRule(RecurringRuleDraft):
    """A saved Recurring Rule."""

    id: int = field(kw_only=True)


@dataclass(frozen=True)
class RuleDefaults:
    """What a new rule's dialog opens with: an empty rule, or one repeating a Transaction (spec 3.3.1 point 9)."""

    account_id: int | None
    transaction_type: TransactionType
    day_of_month: int
    start_date: date
    amount: Decimal | None = None
    currency: str = PLN
    instrument_id: int | None = None
    frequency: Frequency = Frequency.MONTHLY


def new_rule_defaults(today: date, account_id: int | None) -> RuleDefaults:
    """A monthly Deposit on today's day of the month, from its next occurrence."""
    return RuleDefaults(
        account_id,
        TransactionType.DEPOSIT,
        today.day,
        first_occurrence_after(today.day, Frequency.MONTHLY, today),
    )


def repeating(transaction: Transaction, today: date) -> RuleDefaults:
    """A monthly rule repeating a Deposit or Buy on its day of the month, from the next occurrence after today (or
    after the Transaction, if dated ahead), so that an old one brings no backlog of Drafts: a Deposit's amount in its
    currency, a Buy's Actual Amount in PLN."""
    day = transaction.date.day
    foreign = transaction.transaction_type is TransactionType.DEPOSIT and transaction.cash_currency != PLN
    return RuleDefaults(
        transaction.account_id,
        transaction.transaction_type,
        day,
        first_occurrence_after(day, Frequency.MONTHLY, max(transaction.date, today)),
        amount=transaction.quantity if foreign else transaction.actual_amount,
        currency=transaction.cash_currency if foreign else PLN,
        instrument_id=transaction.instrument_id if transaction.transaction_type is TransactionType.BUY else None,
    )


def scheduled_day(day_of_month: int, year: int, month: int) -> date:
    """The occurrence in a month: ``day_of_month``, or the month's last day, moved off a weekend to the Monday."""
    day = date(year, month, min(day_of_month, calendar.monthrange(year, month)[1]))
    if day.weekday() >= SATURDAY:
        day += timedelta(days=7 - day.weekday())
    return day


def _schedule(day_of_month: int, frequency: Frequency, first_month: date) -> Iterator[date]:
    """Every occurrence from the month of ``first_month`` on, ``frequency`` apart."""
    index = first_month.year * 12 + first_month.month - 1
    while True:
        yield scheduled_day(day_of_month, index // 12, index % 12 + 1)
        index += frequency.months


def occurrences(rule: RecurringRuleDraft, until: date) -> list[date]:
    """The rule's occurrences from its start up to ``until`` and its end, both inclusive, oldest first."""
    last = until if rule.end_date is None else min(until, rule.end_date)
    found: list[date] = []
    for day in _schedule(rule.day_of_month, rule.frequency, rule.start_date):
        if day > last:
            return found
        if day >= rule.start_date:
            found.append(day)
    raise AssertionError  # the schedule never ends


def first_occurrence_after(day_of_month: int, frequency: Frequency, day: date) -> date:
    """The first occurrence after ``day`` of a schedule starting in its month: a new rule's default start, so that it
    begins with no backlog of Drafts, also when it repeats a Transaction."""
    return next(due for due in _schedule(day_of_month, frequency, day) if due > day)


def next_occurrence(rule: RecurringRuleDraft, on_or_after: date) -> date | None:
    """The rule's first occurrence on or after the day, ``None`` past its end."""
    for day in _schedule(rule.day_of_month, rule.frequency, rule.start_date):
        if rule.end_date is not None and day > rule.end_date:
            return None
        if day >= max(on_or_after, rule.start_date):
            return day
    raise AssertionError  # the schedule never ends


@dataclass(frozen=True)
class RecurringDraft:
    """An occurrence of a rule (``due``) that no Transaction covers and the user has not skipped."""

    rule: RecurringRule
    due: date

    def link(self, draft: TransactionDraft) -> TransactionDraft:
        """``draft`` naming this occurrence, so that it covers it whatever its day or amount."""
        return replace(draft, recurring_rule_id=self.rule.id, recurring_occurrence=self.due)

    def deposit(self, nbp_rate: NbpRate | None) -> TransactionDraft:
        """The Deposit "Zatwierdź" saves: the rule's amount and currency on the occurrence, a foreign one at the NBP
        Rate (D-1), named after the rule."""
        rule = self.rule
        assert rule.transaction_type is TransactionType.DEPOSIT
        return self.link(
            deposit_or_withdrawal(
                rule.account_id,
                self.due,
                TransactionType.DEPOSIT,
                rule.amount,
                rule.name,
                cash_currency=rule.currency,
                nbp_rate=nbp_rate,
            )
        )


def recurring_drafts(
    rules: Iterable[RecurringRule],
    transactions: Sequence[Transaction],
    skipped: Collection[tuple[int, date]],
    today: date,
    account_id: int | None = None,
) -> list[RecurringDraft]:
    """The Drafts due by ``today`` in the View Scope (``account_id``, ``None`` for Total), oldest first.

    An occurrence is covered by a Transaction linked to it, else by one entered by hand or imported (no link) on the
    rule's Account, of its type and, for a Buy, its Instrument, dated within ``MATCH_WINDOW`` of it: the occurrences
    of every rule, oldest first, each take the nearest such Transaction still free, so one covers one occurrence.
    Amounts are never compared. ``skipped`` holds the (rule id, occurrence) pairs the user skipped.
    """
    linked: set[tuple[int, date | None]] = {
        (t.recurring_rule_id, t.recurring_occurrence) for t in transactions if t.recurring_rule_id is not None
    }
    pending = sorted(
        (
            (day, rule.id, rule)
            for rule in rules
            if rule.active
            for day in occurrences(rule, today)
            if (rule.id, day) not in linked and (rule.id, day) not in skipped
        ),
        key=lambda item: (item[0], item[1]),
    )
    free = [t for t in transactions if t.recurring_rule_id is None]
    drafts = []
    for day, _, rule in pending:
        candidates = [
            t
            for t in free
            if t.account_id == rule.account_id
            and t.transaction_type is rule.transaction_type
            and (rule.transaction_type is not TransactionType.BUY or t.instrument_id == rule.instrument_id)
            and abs(t.date - day) <= MATCH_WINDOW
        ]
        if candidates:
            free.remove(min(candidates, key=lambda t: (abs(t.date - day), t.date, t.id)))
        else:
            drafts.append(RecurringDraft(rule, day))
    return [d for d in drafts if account_id is None or d.rule.account_id == account_id]
