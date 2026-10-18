"""Recurring Rules and their Drafts (issue #97, spec 3.3.1): the schedule, matching Transactions and skips."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from financial_app.domain.recurring import (
    Frequency,
    RecurringDraft,
    RecurringRule,
    RecurringRuleError,
    first_occurrence_after,
    next_occurrence,
    occurrences,
    recurring_drafts,
)
from financial_app.domain.transactions import (
    Transaction,
    TransactionDraft,
    TransactionType,
    buy_or_sell,
    deposit_or_withdrawal,
)


def rule(
    day_of_month: int = 10,
    start: date = date(2026, 1, 1),
    frequency: Frequency = Frequency.MONTHLY,
    end: date | None = None,
    **fields: Any,
) -> RecurringRule:
    values: dict[str, Any] = {
        "id": 1,
        "name": "Wpłata IKE",
        "account_id": 1,
        "transaction_type": TransactionType.DEPOSIT,
        "amount": Decimal(1000),
        "currency": "PLN",
        "frequency": frequency,
        "day_of_month": day_of_month,
        "start_date": start,
        "end_date": end,
    }
    values.update(fields)
    return RecurringRule(**values)


def test_a_monthly_rule_falls_due_each_month_from_its_start_until_the_day() -> None:
    # 10.01.2026 is a Saturday, 10.05.2026 a Sunday: both move to the next Monday
    assert occurrences(rule(), date(2026, 6, 9)) == [
        date(2026, 1, 12),
        date(2026, 2, 10),
        date(2026, 3, 10),
        date(2026, 4, 10),
        date(2026, 5, 11),
    ]


def test_a_day_past_the_months_end_falls_on_its_last_day() -> None:
    # 31.01.2026 is a Saturday (→ 02.02), 28.02 a Saturday (→ 02.03), 30.04 a Thursday
    assert occurrences(rule(31), date(2026, 4, 30)) == [
        date(2026, 2, 2),
        date(2026, 3, 2),
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]


def test_february_of_a_leap_year_ends_on_the_29th() -> None:
    # 29.02.2028 is a Tuesday
    assert occurrences(rule(30, start=date(2028, 2, 1)), date(2028, 2, 29)) == [date(2028, 2, 29)]


def test_a_weekend_shift_may_cross_into_the_next_month() -> None:
    # 31.05.2025 is a Saturday
    assert occurrences(rule(31, start=date(2025, 5, 1)), date(2025, 6, 2)) == [date(2025, 6, 2)]


def test_the_starts_month_sets_the_months_of_a_quarterly_rule() -> None:
    quarterly = rule(15, start=date(2026, 2, 15), frequency=Frequency.QUARTERLY)
    # 15.02.2026 is a Sunday, 15.08.2026 a Saturday
    assert occurrences(quarterly, date(2026, 12, 31)) == [
        date(2026, 2, 16),
        date(2026, 5, 15),
        date(2026, 8, 17),
        date(2026, 11, 16),
    ]


def test_semiannual_and_yearly_rules() -> None:
    semiannual = rule(1, start=date(2026, 3, 1), frequency=Frequency.SEMIANNUAL)
    yearly = rule(1, start=date(2026, 3, 1), frequency=Frequency.YEARLY)
    # 01.03.2026 is a Sunday, 01.09.2026 a Tuesday, 01.03.2027 a Monday
    assert occurrences(semiannual, date(2027, 3, 1)) == [date(2026, 3, 2), date(2026, 9, 1), date(2027, 3, 1)]
    assert occurrences(yearly, date(2027, 3, 1)) == [date(2026, 3, 2), date(2027, 3, 1)]


def test_no_occurrence_before_the_start_or_after_the_end() -> None:
    # The start on the 15th leaves out January's 12th; the end leaves out April
    bounded = rule(start=date(2026, 1, 15), end=date(2026, 3, 31))
    assert occurrences(bounded, date(2026, 12, 31)) == [date(2026, 2, 10), date(2026, 3, 10)]


def test_the_next_occurrence_on_or_after_a_day() -> None:
    assert next_occurrence(rule(), date(2026, 2, 11)) == date(2026, 3, 10)
    assert next_occurrence(rule(), date(2026, 3, 10)) == date(2026, 3, 10)
    assert next_occurrence(rule(end=date(2026, 3, 1)), date(2026, 3, 2)) is None


def test_a_new_rule_starts_at_its_first_occurrence_after_the_day() -> None:
    # 10.10.2026 is a Saturday, so the occurrence that month is 12.10
    assert first_occurrence_after(10, Frequency.MONTHLY, date(2026, 10, 11)) == date(2026, 10, 12)
    assert first_occurrence_after(10, Frequency.MONTHLY, date(2026, 10, 12)) == date(2026, 11, 10)
    assert first_occurrence_after(5, Frequency.QUARTERLY, date(2026, 10, 15)) == date(2027, 1, 5)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"name": "  "}, "Podaj nazwę reguły."),
        ({"amount": Decimal(0)}, "Kwota musi być większa od zera."),
        ({"day_of_month": 32}, "Dzień miesiąca musi być od 1 do 31."),
        ({"transaction_type": TransactionType.BUY}, "Wybierz instrument."),
        ({"end_date": date(2025, 12, 31)}, "Data końca nie może być przed datą początku."),
        ({"transaction_type": TransactionType.SELL}, "Reguła cykliczna może być tylko wpłatą albo kupnem."),
    ],
)
def test_a_rule_is_checked_with_polish_messages(fields: dict[str, Any], message: str) -> None:
    with pytest.raises(RecurringRuleError, match=message):
        rule(**fields)


def deposit(id: int, day: date, account_id: int = 1, **link: Any) -> Transaction:
    draft = deposit_or_withdrawal(account_id, day, TransactionType.DEPOSIT, Decimal(700))
    return replace(draft, **link).with_id(id)


def due(drafts: list[RecurringDraft]) -> list[tuple[int, date]]:
    return [(d.rule.id, d.due) for d in drafts]


TODAY = date(2026, 4, 15)


def test_every_occurrence_up_to_today_is_a_draft_without_a_transaction() -> None:
    assert due(recurring_drafts([rule()], [], set(), TODAY)) == [
        (1, date(2026, 1, 12)),
        (1, date(2026, 2, 10)),
        (1, date(2026, 3, 10)),
        (1, date(2026, 4, 10)),
    ]


def test_a_transaction_linked_to_an_occurrence_covers_it_whatever_its_day_and_amount() -> None:
    linked = deposit(1, date(2026, 3, 30), recurring_rule_id=1, recurring_occurrence=date(2026, 2, 10))
    assert due(recurring_drafts([rule(start=date(2026, 2, 1))], [linked], set(), TODAY)) == [
        (1, date(2026, 3, 10)),
        (1, date(2026, 4, 10)),
    ]


def test_a_transaction_within_seven_days_covers_an_occurrence_whatever_its_amount() -> None:
    transactions = [deposit(1, date(2026, 3, 3)), deposit(2, date(2026, 4, 18)), deposit(3, date(2026, 1, 30))]
    # 03.03 is 7 days before 10.03, 18.04 is 8 days after 10.04, 30.01 is 18 days after 12.01
    assert due(recurring_drafts([rule()], transactions, set(), TODAY)) == [
        (1, date(2026, 1, 12)),
        (1, date(2026, 2, 10)),
        (1, date(2026, 4, 10)),
    ]


def test_a_transaction_covers_one_occurrence_only_the_oldest_taking_the_nearest() -> None:
    # Two rules on the same Account falling due two days apart: 10.03 and 12.03
    other = rule(12, id=2, start=date(2026, 3, 1))
    first = rule(start=date(2026, 3, 1), end=date(2026, 3, 31))
    transactions = [deposit(1, date(2026, 3, 11)), deposit(2, date(2026, 3, 16))]
    # 10.03 takes 11.03, the nearest; 12.03 (a Thursday) takes 16.03; April's 10th and 13th stay
    assert due(recurring_drafts([first, other], transactions, set(), TODAY)) == [(2, date(2026, 4, 13))]


def test_a_transaction_of_another_account_type_or_instrument_covers_nothing() -> None:
    buy_rule = rule(id=2, transaction_type=TransactionType.BUY, instrument_id=7, start=date(2026, 4, 1))
    deposit_rule = rule(start=date(2026, 4, 1))
    transactions = [
        deposit(1, date(2026, 4, 10), account_id=2),
        buy_or_sell(1, date(2026, 4, 10), TransactionType.BUY, 8, Decimal(1), Decimal(100)).with_id(2),
    ]
    assert due(recurring_drafts([deposit_rule, buy_rule], transactions, set(), TODAY)) == [
        (1, date(2026, 4, 10)),
        (2, date(2026, 4, 10)),
    ]
    bought = buy_or_sell(1, date(2026, 4, 9), TransactionType.BUY, 7, Decimal(1), Decimal(100)).with_id(3)
    assert due(recurring_drafts([buy_rule], [bought], set(), TODAY)) == []


def test_a_transaction_linked_to_one_occurrence_never_covers_another() -> None:
    linked = deposit(1, date(2026, 4, 10), recurring_rule_id=1, recurring_occurrence=date(2026, 3, 10))
    april = rule(start=date(2026, 3, 1))
    assert due(recurring_drafts([april], [linked], set(), TODAY)) == [(1, date(2026, 4, 10))]


def test_skipped_occurrences_and_inactive_rules_give_no_drafts() -> None:
    skipped = {(1, date(2026, 3, 10))}
    assert due(recurring_drafts([rule(start=date(2026, 3, 1))], [], skipped, TODAY)) == [(1, date(2026, 4, 10))]
    assert recurring_drafts([rule(active=False)], [], set(), TODAY) == []


def test_drafts_follow_the_view_scope_oldest_first() -> None:
    ike = rule(start=date(2026, 4, 1))
    other = rule(5, id=2, account_id=2, start=date(2026, 4, 1))
    assert due(recurring_drafts([ike, other], [], set(), TODAY)) == [(2, date(2026, 4, 6)), (1, date(2026, 4, 10))]
    assert due(recurring_drafts([ike, other], [], set(), TODAY, account_id=2)) == [(2, date(2026, 4, 6))]


def test_confirming_a_deposit_draft_saves_the_rules_amount_on_the_occurrence_with_its_link() -> None:
    draft = RecurringDraft(rule(), date(2026, 4, 10))
    assert draft.deposit(None) == TransactionDraft(
        1,
        date(2026, 4, 10),
        TransactionType.DEPOSIT,
        Decimal(1000),
        "Wpłata IKE",
        recurring_rule_id=1,
        recurring_occurrence=date(2026, 4, 10),
    )


def test_a_transaction_names_its_occurrence_with_its_rule() -> None:
    with pytest.raises(ValueError, match="termin"):
        TransactionDraft(1, TODAY, TransactionType.DEPOSIT, Decimal(1), recurring_rule_id=1)
