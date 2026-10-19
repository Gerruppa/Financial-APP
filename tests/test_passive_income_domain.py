"""The passive-income calendar (issue #93, spec 10): Dividends and interest received, the coupons forecast, by month,
against the Monthly Income Goal."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.passive_income import (
    IncomeItem,
    IncomeKind,
    forecast_deposit_interest,
    income_by_month,
    monthly_average,
    parse_income_goal,
    received_income,
)
from financial_app.domain.term_deposits import (
    Capitalization,
    InterestDraft,
    TermDeposit,
    TermUnit,
    deposit_drafts,
)
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell, dividend, drip

IKE, XTB = 1, 2
PZU = 10


def test_dividends_drips_and_interest_are_received_income_net_of_their_tax() -> None:
    items = received_income(
        [
            TransactionDraft(IKE, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(1000)),
            buy_or_sell(IKE, date(2026, 1, 3), TransactionType.BUY, PZU, Decimal(10), Decimal(50)),
            dividend(IKE, date(2026, 2, 3), Decimal(100), Decimal(19), instrument_id=PZU),
            drip(IKE, date(2026, 3, 3), PZU, Decimal(1), Decimal(40)),
            dividend(XTB, date(2026, 3, 31), Decimal(10), Decimal(2)),
            dividend(IKE, date(2026, 4, 1), Decimal(30), lot_id=7),
        ]
    )

    assert items == [
        IncomeItem(date(2026, 2, 3), IncomeKind.DIVIDENDS, IKE, Decimal(81), instrument_id=PZU),
        IncomeItem(date(2026, 3, 3), IncomeKind.DIVIDENDS, IKE, Decimal(40), instrument_id=PZU),
        IncomeItem(date(2026, 3, 31), IncomeKind.INTEREST, XTB, Decimal(8)),
        IncomeItem(date(2026, 4, 1), IncomeKind.BOND_INTEREST, IKE, Decimal(30)),
    ]


def _items() -> list[IncomeItem]:
    return [
        IncomeItem(date(2025, 12, 31), IncomeKind.DIVIDENDS, IKE, Decimal(5)),
        IncomeItem(date(2026, 1, 10), IncomeKind.DIVIDENDS, IKE, Decimal(100)),
        IncomeItem(date(2026, 1, 20), IncomeKind.INTEREST, XTB, Decimal(10)),
        IncomeItem(date(2026, 3, 5), IncomeKind.BOND_INTEREST, IKE, Decimal(40)),
        IncomeItem(date(2026, 11, 5), IncomeKind.BOND_INTEREST, IKE, Decimal(45), forecast=True),
    ]


def test_the_months_of_a_year_sum_the_received_and_the_forecast_by_kind() -> None:
    months = income_by_month(_items(), 2026, None)

    assert [m.month for m in months] == [date(2026, n, 1) for n in range(1, 13)]
    january, march, november = months[0], months[2], months[10]
    assert january.received == {IncomeKind.DIVIDENDS: Decimal(100), IncomeKind.INTEREST: Decimal(10)}
    assert january.total == Decimal(110)
    assert march.received == {IncomeKind.BOND_INTEREST: Decimal(40)}
    assert november.forecast == {IncomeKind.BOND_INTEREST: Decimal(45)}
    assert (november.received_total, november.forecast_total, november.total) == (Decimal(0), Decimal(45), Decimal(45))
    assert months[1].total == 0


def test_the_months_follow_the_view_scope() -> None:
    january = income_by_month(_items(), 2026, XTB)[0]

    assert january.received == {IncomeKind.INTEREST: Decimal(10)}


def test_a_months_progress_toward_the_goal() -> None:
    january = income_by_month(_items(), 2026, None)[0]

    assert january.progress(Decimal(200)) == Decimal("0.55")
    assert january.progress(None) is None


def test_the_monthly_average_counts_the_twelve_months_before_this_one() -> None:
    # 1.02.2025 to 31.01.2026: 5 + 100 + 10 (March is after January, the forecast is no income yet)
    assert monthly_average(_items(), date(2026, 2, 14), None) == Decimal(115) / 12
    assert monthly_average(_items(), date(2026, 2, 14), XTB) == Decimal(10) / 12


@pytest.mark.parametrize(
    ("text", "goal"), [("", None), ("  ", None), ("1500", Decimal(1500)), ("1 500,50", Decimal("1500.50"))]
)
def test_the_goal_is_a_positive_amount_or_none(text: str, goal: Decimal | None) -> None:
    assert parse_income_goal(text) == goal


@pytest.mark.parametrize("text", ["0", "-5", "abc"])
def test_a_goal_that_is_no_positive_amount_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="Cel"):
        parse_income_goal(text)


def test_term_deposit_interest_is_received_and_its_periods_not_paid_yet_are_forecast() -> None:
    savings = Account("Lokaty", "mBank", AccountType.DEPOSIT, ("PLN",), id=3)
    lokata = TermDeposit(
        id=5,
        account_id=3,
        name="Lokata 3M",
        principal=Decimal(10000),
        start_date=date(2026, 1, 15),
        term_count=3,
        term_unit=TermUnit.MONTHS,
        annual_rate=Decimal(6),
        capitalization=Capitalization.AT_MATURITY,
    )
    linked = replace(
        dividend(3, date(2026, 4, 15), Decimal("147.95"), Decimal("28.11")),
        term_deposit_id=5,
        term_deposit_period=date(2026, 4, 15),
    )
    # The period's interest, then the deposit's maturity
    draft, _ = deposit_drafts([lokata], [savings], [], date(2026, 5, 1), None)
    assert isinstance(draft, InterestDraft)

    assert received_income([linked]) == [
        IncomeItem(date(2026, 4, 15), IncomeKind.DEPOSIT_INTEREST, 3, Decimal("119.84"))
    ]
    assert forecast_deposit_interest([draft]) == [
        IncomeItem(date(2026, 4, 15), IncomeKind.DEPOSIT_INTEREST, 3, Decimal("119.84"), forecast=True)
    ]
