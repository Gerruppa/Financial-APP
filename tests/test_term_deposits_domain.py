"""Term Deposits (issue #160): their interest periods, accrued interest, Drafts and the capital they hold.

The expected amounts are worked out by hand: gross = capital × rate × days / 365, rounded to the grosz; Belka 19% of
it, rounded to the grosz; a capitalised period adds its net interest to the next one's capital.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.term_deposits import (
    Accruals,
    AccruedInterest,
    Capitalization,
    DepositMaturityDraft,
    InterestDraft,
    TermDeposit,
    TermDepositError,
    TermUnit,
    accrued_interest,
    deposit_drafts,
    deposit_rows,
    interest_periods,
    locked_capital,
    needs_capital,
    paid_periods,
    tax_rates_of,
)
from financial_app.domain.transactions import Transaction, TransactionType, deposit_or_withdrawal, dividend

BELKA = Decimal("0.19")


def deposit(**fields: Any) -> TermDeposit:
    values: dict[str, Any] = {
        "id": 1,
        "account_id": 1,
        "name": "Lokata 3M",
        "principal": Decimal(10000),
        "start_date": date(2026, 1, 15),
        "term_count": 3,
        "term_unit": TermUnit.MONTHS,
        "annual_rate": Decimal(6),
        "capitalization": Capitalization.AT_MATURITY,
    }
    values.update(fields)
    return TermDeposit(**values)


def test_a_deposit_capitalised_at_maturity_pays_its_interest_once_on_its_maturity_day() -> None:
    # 15.01 to 15.04.2026 is 90 days: 10 000 × 6% × 90 / 365 = 147,945… → 147,95 zł; Belka 28,1105 → 28,11 zł
    (period,) = interest_periods(deposit(), BELKA)

    assert deposit().maturity == date(2026, 4, 15)
    assert (period.number, period.start, period.end) == (1, date(2026, 1, 15), date(2026, 4, 15))
    assert (period.capital, period.gross, period.tax, period.net) == (
        Decimal(10000),
        Decimal("147.95"),
        Decimal("28.11"),
        Decimal("119.84"),
    )


def test_a_monthly_capitalised_deposit_adds_each_months_net_interest_to_the_next_months_capital() -> None:
    periods = interest_periods(deposit(capitalization=Capitalization.MONTHLY), BELKA)

    # 31 days: 50,958… → 50,96, Belka 9,68; 28 days of 10 041,28: 46,217… → 46,22, Belka 8,78; 31 days of
    # 10 078,72: 51,360… → 51,36, Belka 9,76
    assert [(p.start, p.end, p.capital, p.gross, p.tax) for p in periods] == [
        (date(2026, 1, 15), date(2026, 2, 15), Decimal(10000), Decimal("50.96"), Decimal("9.68")),
        (date(2026, 2, 15), date(2026, 3, 15), Decimal("10041.28"), Decimal("46.22"), Decimal("8.78")),
        (date(2026, 3, 15), date(2026, 4, 15), Decimal("10078.72"), Decimal("51.36"), Decimal("9.76")),
    ]


def test_the_last_period_ends_on_maturity_when_the_term_is_not_a_whole_number_of_periods() -> None:
    days = deposit(term_count=45, term_unit=TermUnit.DAYS, capitalization=Capitalization.MONTHLY)
    periods = interest_periods(days, BELKA)

    assert [(p.number, p.start, p.end) for p in periods] == [
        (1, date(2026, 1, 15), date(2026, 2, 15)),
        (2, date(2026, 2, 15), date(2026, 3, 1)),
    ]


def test_a_deposit_broken_before_maturity_forfeits_the_interest_of_the_period_it_was_broken_in() -> None:
    broken = deposit(capitalization=Capitalization.MONTHLY, closed_on=date(2026, 3, 20))

    assert [p.end for p in interest_periods(broken, BELKA)] == [date(2026, 2, 15), date(2026, 3, 15)]


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"name": " "}, "Podaj nazwę lokaty."),
        ({"principal": Decimal(0)}, "Kwota lokaty musi być większa od zera."),
        ({"principal": Decimal("100.001")}, "Kwotę lokaty podaj z dokładnością do grosza."),
        ({"term_count": 0}, "Okres lokaty musi być większy od zera."),
        ({"annual_rate": Decimal(0)}, "Oprocentowanie musi być większe od zera."),
        ({"closed_on": date(2026, 1, 14)}, "Data zakończenia nie może być przed założeniem lokaty."),
        ({"closed_on": date(2026, 4, 16)}, "Data zakończenia nie może być po terminie zapadalności."),
    ],
)
def test_a_deposit_with_a_field_that_does_not_make_one_is_refused_in_polish(
    fields: dict[str, Any], message: str
) -> None:
    with pytest.raises(TermDepositError, match=message):
        deposit(**fields)


def interest(day: date, gross: str, tax: str, account_id: int = 1, **links: Any) -> Transaction:
    draft = replace(dividend(account_id, day, Decimal(gross), Decimal(tax)), **links)
    return Transaction(**{**vars(draft), "id": 100 + day.toordinal() % 100})


def test_interest_accrues_day_by_day_and_a_period_not_paid_yet_stays_accrued() -> None:
    monthly = deposit(capitalization=Capitalization.MONTHLY)

    # The first period whole (50,96 less 9,68) and 14 days of the second's 10 041,28: 23,108… → 23,11, Belka 4,39
    accrued = accrued_interest(monthly, BELKA, date(2026, 3, 1), paid_periods([monthly], []))

    assert (accrued.gross, accrued.tax, accrued.net) == (Decimal("74.07"), Decimal("14.07"), Decimal("60.00"))


def test_a_period_paid_by_the_day_leaves_the_accrued_interest_for_the_cash() -> None:
    monthly = deposit(capitalization=Capitalization.MONTHLY)
    paid = paid_periods([monthly], [interest(date(2026, 2, 16), "50.96", "9.68")])

    assert accrued_interest(monthly, BELKA, date(2026, 3, 1), paid).net == Decimal("18.72")
    # The day before the interest was entered, the period still counts as accrued
    assert accrued_interest(monthly, BELKA, date(2026, 2, 15), paid).net == Decimal("41.28")


def test_nothing_accrues_before_the_start_nor_after_a_deposit_ended_and_was_paid() -> None:
    whole = deposit()
    paid = paid_periods([whole], [interest(date(2026, 4, 15), "147.95", "28.11")])

    assert accrued_interest(whole, BELKA, date(2026, 1, 15), paid).net == 0
    assert accrued_interest(whole, BELKA, date(2026, 6, 1), paid).net == 0


def test_interest_linked_to_a_period_pays_it_whatever_its_day_and_unlinked_interest_near_the_day_pays_it_too() -> None:
    monthly = deposit(capitalization=Capitalization.MONTHLY)
    linked = interest(date(2026, 4, 1), "46.22", "8.78", term_deposit_id=1, term_deposit_period=date(2026, 3, 15))
    by_hand = interest(date(2026, 2, 18), "50.96", "9.68")
    elsewhere = interest(date(2026, 4, 15), "51.36", "9.76", account_id=2)

    assert paid_periods([monthly], [linked, by_hand, elsewhere]) == {
        (1, date(2026, 2, 15)): date(2026, 2, 18),
        (1, date(2026, 3, 15)): date(2026, 4, 1),
    }


SAVINGS = Account("Lokaty mBank", "mBank", AccountType.DEPOSIT, ("PLN",), id=1)
OTHER = Account("Lokaty PKO", "PKO BP", AccountType.DEPOSIT, ("PLN",), id=2)


def test_each_period_ended_and_not_paid_is_an_interest_draft_saving_linked_interest() -> None:
    monthly = deposit(capitalization=Capitalization.MONTHLY)
    paid = [interest(date(2026, 2, 15), "50.96", "9.68")]

    (draft,) = deposit_drafts([monthly], [SAVINGS], paid, date(2026, 4, 1), None)

    assert isinstance(draft, InterestDraft)
    assert draft.due == date(2026, 3, 15)
    saved = draft.transaction()
    assert (saved.account_id, saved.date, saved.gross, saved.withholding_tax, saved.actual_amount) == (
        1,
        date(2026, 3, 15),
        Decimal("46.22"),
        Decimal("8.78"),
        Decimal("37.44"),
    )
    assert (saved.instrument_id, saved.term_deposit_id, saved.term_deposit_period) == (None, 1, date(2026, 3, 15))
    assert saved.comment == "Odsetki Lokata 3M · okres 2"


def test_a_deposit_reaching_maturity_drafts_its_last_interest_and_its_maturity_renewing_its_whole_capital() -> None:
    drafts = deposit_drafts([deposit(renew=True)], [SAVINGS], [], date(2026, 4, 15), None)

    assert [type(d) for d in drafts] == [InterestDraft, DepositMaturityDraft]
    matured = drafts[1]
    assert isinstance(matured, DepositMaturityDraft)
    assert matured.final_capital == Decimal("10119.84")
    renewed = matured.renewal(Decimal("5.5"))
    assert (renewed.start_date, renewed.principal, renewed.annual_rate, renewed.maturity, renewed.renew) == (
        date(2026, 4, 15),
        Decimal("10119.84"),
        Decimal("5.5"),
        date(2026, 7, 15),
        True,
    )


def test_a_closed_deposit_drafts_no_maturity_and_drafts_follow_the_view_scope() -> None:
    closed = deposit(closed_on=date(2026, 4, 15))
    paid = [interest(date(2026, 4, 15), "147.95", "28.11")]
    elsewhere = deposit(id=2, account_id=2)

    assert deposit_drafts([closed], [SAVINGS], paid, date(2026, 5, 1), None) == []
    assert [d.deposit.id for d in deposit_drafts([elsewhere], [SAVINGS, OTHER], [], date(2026, 5, 1), 1)] == []
    assert len(deposit_drafts([elsewhere], [SAVINGS, OTHER], [], date(2026, 5, 1), 2)) == 2


def test_the_accrued_interest_of_each_account_sums_its_deposits() -> None:
    monthly = deposit(capitalization=Capitalization.MONTHLY)
    whole = deposit(id=2)
    elsewhere = deposit(id=3, account_id=2, start_date=date(2026, 3, 1))

    accrued = Accruals([monthly, whole, elsewhere], tax_rates_of([SAVINGS, OTHER]), []).on(date(2026, 3, 1))

    # 45 days of 10 000 at 6%: 73,972… → 73,97, Belka 14,05
    assert accrued == {1: AccruedInterest(Decimal("148.04"), Decimal("28.12"))}


def test_a_running_deposit_holds_its_principal_from_its_start_to_the_day_before_it_ends() -> None:
    monthly = deposit(capitalization=Capitalization.MONTHLY)
    broken = deposit(id=2, closed_on=date(2026, 2, 1))

    assert locked_capital([monthly, broken], date(2026, 1, 14)) == {}
    assert locked_capital([monthly, broken], date(2026, 1, 15)) == {1: Decimal(20000)}
    assert locked_capital([monthly, broken], date(2026, 3, 1)) == {1: Decimal(10000)}
    assert locked_capital([monthly, broken], date(2026, 4, 15)) == {}


def test_the_deposits_list_shows_each_running_deposit_with_its_accrued_interest_and_break_value() -> None:
    monthly = deposit(capitalization=Capitalization.MONTHLY)
    ended = deposit(id=2, name="Lokata zimowa", closed_on=date(2026, 2, 1))
    elsewhere = deposit(id=3, account_id=2)

    (row,) = deposit_rows([monthly, ended, elsewhere], [SAVINGS, OTHER], [], date(2026, 3, 1), 1)

    assert row.deposit == monthly
    assert row.accrued.net == Decimal("60.00")
    # Broken today it pays the principal and the first month's 41,28 zł; the second month's is forfeited
    assert row.break_value == Decimal("10041.28")
    assert row.days_left == 45


def test_interest_paid_before_its_period_ends_stops_accruing_once_in_the_cash() -> None:
    monthly = deposit(capitalization=Capitalization.MONTHLY)
    paid = paid_periods([monthly], [interest(date(2026, 2, 12), "50.96", "9.68")])

    # Paid on 12.02 for the period ending 15.02: from then on only the cash holds it
    assert accrued_interest(monthly, BELKA, date(2026, 2, 13), paid).net == 0


def test_the_deposits_list_matches_entered_interest_as_the_value_does() -> None:
    ended = deposit(id=2, name="Lokata zimowa", start_date=date(2025, 11, 10), closed_on=date(2026, 2, 10))
    running = deposit(capitalization=Capitalization.MONTHLY)
    # Entered by hand on 12.02: the nearest period is the ended deposit's (10.02), not the running one's (15.02)
    entered = [interest(date(2026, 2, 12), "147.95", "28.11")]

    (row,) = deposit_rows([ended, running], [SAVINGS], entered, date(2026, 2, 16), None)

    assert row.accrued == Accruals([ended, running], tax_rates_of([SAVINGS]), entered).on(date(2026, 2, 16))[1]


def test_a_new_deposit_needs_its_capital_paid_in_unless_the_account_holds_it_on_its_start() -> None:
    paid_in = Transaction(
        **{
            **vars(deposit_or_withdrawal(1, date(2026, 1, 10), TransactionType.DEPOSIT, Decimal(10000))),
            "id": 1,
        }
    )

    assert needs_capital([paid_in], 1, date(2026, 1, 15), Decimal(10000)) is False
    assert needs_capital([paid_in], 1, date(2026, 1, 15), Decimal("10000.01")) is True
    # Cash paid in after the start does not hold it on the start
    assert needs_capital([paid_in], 1, date(2026, 1, 9), Decimal(100)) is True
    assert needs_capital([paid_in], 2, date(2026, 1, 15), Decimal(100)) is True
