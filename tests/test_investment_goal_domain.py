"""The Investment Goal of a View Scope (issue #96): its value given directly or for FIRE, the progress, the default
monthly deposit and the real forecast."""

from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.investment_goal import (
    GoalError,
    GoalMode,
    GoalTexts,
    InvestmentGoal,
    average_monthly_deposits,
    forecast,
    parse_goal,
    rules_monthly_deposits,
)
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.recurring import Frequency, RecurringRule
from financial_app.domain.transactions import TransactionType

TODAY = date(2026, 10, 17)


def _day(day: date, net_deposits: int, account_net_deposits: int = 0) -> DayValue:
    return DayValue(
        day=day,
        accounts={},
        classes={},
        net_deposits=Decimal(net_deposits),
        account_net_deposits={1: Decimal(account_net_deposits)},
        unpriced=frozenset(),
    )


def test_a_fire_goal_is_the_yearly_expenses_over_the_safe_withdrawal_rate() -> None:
    fire = InvestmentGoal(None, GoalMode.FIRE, yearly_expenses=Decimal(60000))
    assert fire.target == Decimal(1_500_000)

    three_percent = InvestmentGoal(None, GoalMode.FIRE, yearly_expenses=Decimal(60000), withdrawal_rate=Decimal(3))
    assert three_percent.target == Decimal(2_000_000)

    assert InvestmentGoal(1, GoalMode.AMOUNT, amount=Decimal(1_000_000)).target == Decimal(1_000_000)


@pytest.mark.parametrize(
    ("goal", "message"),
    [
        (lambda: InvestmentGoal(None, GoalMode.AMOUNT), "Podaj kwotę celu większą od zera."),
        (lambda: InvestmentGoal(None, GoalMode.AMOUNT, amount=Decimal(0)), "Podaj kwotę celu większą od zera."),
        (lambda: InvestmentGoal(None, GoalMode.FIRE), "Podaj roczne wydatki większe od zera."),
        (
            lambda: InvestmentGoal(None, GoalMode.FIRE, yearly_expenses=Decimal(1), withdrawal_rate=Decimal(0)),
            "Stopa wypłaty musi być większa od 0 % i mniejsza od 100 %.",
        ),
        (
            lambda: InvestmentGoal(None, GoalMode.AMOUNT, amount=Decimal(1), real_return=Decimal(-100)),
            "Stopa zwrotu musi być większa od -100 %.",
        ),
    ],
)
def test_a_goal_without_a_positive_value_is_refused(goal: object, message: str) -> None:
    with pytest.raises(GoalError, match=message):
        goal()  # type: ignore[operator]


def test_the_default_monthly_deposit_is_the_average_over_the_last_twelve_months() -> None:
    history = [_day(date(2025, 1, 2), 10000), _day(date(2025, 10, 16), 20000), _day(TODAY, 32000)]

    # From 17.10.2025: 12 000 zł in the twelve months
    assert average_monthly_deposits(history, None, TODAY) == Decimal(1000)


def test_a_shorter_history_averages_over_the_months_it_has() -> None:
    history = [_day(date(2026, 4, 18), 3000, 6000), _day(TODAY, 3000, 6000)]

    # 182 days, about six months; the Account's own Net Deposits in its scope
    assert average_monthly_deposits(history, None, TODAY).quantize(Decimal(1)) == Decimal(502)
    assert average_monthly_deposits(history, 1, TODAY).quantize(Decimal(1)) == Decimal(1003)
    assert average_monthly_deposits([], None, TODAY) == Decimal(0)


def _rule(
    rule_id: int,
    kind: TransactionType,
    amount: int,
    frequency: Frequency = Frequency.MONTHLY,
    *,
    account_id: int = 1,
    currency: str = "PLN",
    target_account_id: int | None = None,
    start_date: date = date(2026, 1, 10),
    end_date: date | None = None,
    active: bool = True,
) -> RecurringRule:
    return RecurringRule(
        f"Reguła {rule_id}",
        account_id,
        kind,
        Decimal(amount),
        currency,
        frequency,
        10,
        start_date,
        end_date,
        instrument_id=7 if kind is TransactionType.BUY else None,
        active=active,
        target_account_id=target_account_id,
        id=rule_id,
    )


def test_deposit_rules_give_the_monthly_deposit_per_month_in_pln() -> None:
    rules = [
        _rule(1, TransactionType.DEPOSIT, 1000),
        _rule(2, TransactionType.DEPOSIT, 3000, Frequency.QUARTERLY),
        _rule(3, TransactionType.DEPOSIT, 600, Frequency.SEMIANNUAL),
        _rule(4, TransactionType.DEPOSIT, 100, Frequency.YEARLY, currency="EUR"),
    ]

    # 1 000 + 3 000 / 3 + 600 / 6 + 100 € × 4,20 / 12
    assert rules_monthly_deposits(rules, None, TODAY, {"EUR": Decimal("4.2")}) == Decimal(2135)


def test_the_total_counts_the_active_deposit_rules_still_running() -> None:
    rules = [
        _rule(1, TransactionType.DEPOSIT, 1000),
        _rule(2, TransactionType.DEPOSIT, 200, account_id=2),
        # Starting ahead still counts
        _rule(3, TransactionType.DEPOSIT, 50, start_date=date(2027, 1, 10)),
        # A Buy spends cash already deposited, a Cost leaves Net Deposits alone, a Cash Transfer stays within
        _rule(4, TransactionType.BUY, 500),
        _rule(5, TransactionType.COST, 30),
        _rule(6, TransactionType.CASH_TRANSFER, 400, target_account_id=2),
        # Paused, or ended before today
        _rule(7, TransactionType.DEPOSIT, 9000, active=False),
        _rule(8, TransactionType.DEPOSIT, 9000, end_date=date(2026, 10, 16)),
    ]

    assert rules_monthly_deposits(rules, None, TODAY, {}) == Decimal(1250)
    assert rules_monthly_deposits(rules[3:], None, TODAY, {}) is None


def test_an_accounts_view_adds_cash_transfers_into_it_and_takes_off_those_out_of_it() -> None:
    rules = [
        _rule(1, TransactionType.DEPOSIT, 1000),
        _rule(2, TransactionType.DEPOSIT, 200, account_id=2),
        _rule(3, TransactionType.CASH_TRANSFER, 300, account_id=2, target_account_id=1),
        _rule(4, TransactionType.CASH_TRANSFER, 600, Frequency.QUARTERLY, target_account_id=3),
        # Ends today: still running
        _rule(5, TransactionType.CASH_TRANSFER, 50, account_id=3, target_account_id=2, end_date=TODAY),
    ]

    assert rules_monthly_deposits(rules, 1, TODAY, {}) == Decimal(1100)
    assert rules_monthly_deposits(rules, 2, TODAY, {}) == Decimal(-50)
    assert rules_monthly_deposits(rules, 3, TODAY, {}) == Decimal(150)
    assert rules_monthly_deposits(rules, 4, TODAY, {}) is None


def test_without_growth_the_goal_is_reached_when_the_deposits_add_up_to_it() -> None:
    goal = InvestmentGoal(None, GoalMode.AMOUNT, amount=Decimal(12000), real_return=Decimal(0))

    result = forecast(goal, Decimal(0), Decimal(1000), TODAY)

    assert result.progress == Decimal(0)
    assert not result.reached
    assert result.reached_on == date(2027, 10, 17)


def test_growth_alone_doubles_the_value_in_a_year_at_a_hundred_percent() -> None:
    goal = InvestmentGoal(None, GoalMode.AMOUNT, amount=Decimal(99990), real_return=Decimal(100))

    result = forecast(goal, Decimal(50000), Decimal(0), TODAY)

    assert result.reached_on == date(2027, 10, 17)


def test_a_goal_already_reached_and_one_out_of_reach() -> None:
    goal = InvestmentGoal(None, GoalMode.AMOUNT, amount=Decimal(1000), real_return=Decimal(0))

    reached = forecast(goal, Decimal(1500), Decimal(0), TODAY)
    assert reached.reached
    assert reached.progress == Decimal("1.5")

    out_of_reach = forecast(goal, Decimal(500), Decimal(0), TODAY)
    assert not out_of_reach.reached
    assert out_of_reach.reached_on is None


def test_a_target_date_gives_the_monthly_deposit_needed() -> None:
    goal = InvestmentGoal(
        None, GoalMode.AMOUNT, amount=Decimal(130000), real_return=Decimal(0), target_date=date(2036, 10, 17)
    )

    assert forecast(goal, Decimal(10000), Decimal(500), TODAY).required_monthly == Decimal(1000)

    growing = InvestmentGoal(
        None, GoalMode.AMOUNT, amount=Decimal(99990), real_return=Decimal(100), target_date=date(2027, 10, 17)
    )
    # Growth alone gets there by then
    assert forecast(growing, Decimal(50000), Decimal(0), TODAY).required_monthly == Decimal(0)

    past = InvestmentGoal(None, GoalMode.AMOUNT, amount=Decimal(1000), target_date=date(2026, 1, 1))
    assert forecast(past, Decimal(0), Decimal(0), TODAY).required_monthly is None


def test_the_dialogs_texts_read_into_a_goal_and_an_edit_shows_them_again() -> None:
    texts = GoalTexts(
        yearly_expenses="60 000", withdrawal_rate="3,5", target_date="31.12.2040", real_return="4", monthly_deposit=""
    )

    goal = parse_goal(2, GoalMode.FIRE, texts)

    assert goal == InvestmentGoal(
        2,
        GoalMode.FIRE,
        yearly_expenses=Decimal(60000),
        withdrawal_rate=Decimal("3.5"),
        target_date=date(2040, 12, 31),
        real_return=Decimal(4),
    )
    assert parse_goal(2, GoalMode.FIRE, GoalTexts.of(goal)) == goal
    # The amount typed in FIRE mode is not the goal's
    assert parse_goal(None, GoalMode.FIRE, GoalTexts(amount="abc", yearly_expenses="1")).amount is None


@pytest.mark.parametrize(
    ("texts", "message"),
    [
        (GoalTexts(amount="milion"), "Kwota celu: wpisz liczbę, np. 1 000 000."),
        (GoalTexts(amount="1", target_date="2040"), "Data docelowa: wpisz datę jak 31.12.2040."),
        (GoalTexts(amount="1", real_return="dużo"), "Stopa zwrotu: wpisz liczbę, np. 4."),
        (GoalTexts(amount="1", monthly_deposit="x"), "Miesięczna wpłata: wpisz liczbę albo zostaw puste."),
    ],
)
def test_a_text_that_does_not_read_names_its_field(texts: GoalTexts, message: str) -> None:
    with pytest.raises(GoalError, match=message):
        parse_goal(None, GoalMode.AMOUNT, texts)
