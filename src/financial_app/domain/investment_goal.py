"""The Investment Goal of a View Scope (issue #96): the value in PLN it aims at, entered directly or worked out for
FIRE from yearly expenses and a safe withdrawal rate, and its real forecast in today's złoty.

The forecast compounds the expected real yearly return monthly and adds the monthly deposit at each month's end; by
default that deposit is the View Scope's average monthly Net Deposits over the last twelve months (or the shorter
History there is).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from financial_app.domain.bonds import add_months
from financial_app.domain.formatting import format_date, format_exact, format_number, parse_date, parse_number
from financial_app.domain.portfolio_history import DayValue

# Percent: 4% gives the FIRE goal of 25 × the yearly expenses
DEFAULT_WITHDRAWAL_RATE = Decimal(4)
# Percent a year, after inflation
DEFAULT_REAL_RETURN = Decimal(4)
# How far ahead the forecast looks before calling a goal out of reach
FORECAST_MONTHS = 100 * 12
# The months the default monthly deposit averages over
AVERAGE_MONTHS = 12
# The average month of a 365.25-day year, for a History shorter than AVERAGE_MONTHS
DAYS_A_MONTH = Decimal("30.4375")


class GoalError(ValueError):
    """An Investment Goal that cannot be saved; the message is Polish, for the user."""


class GoalMode(StrEnum):
    AMOUNT = "amount"
    FIRE = "fire"


@dataclass(frozen=True)
class InvestmentGoal:
    """The goal of the View Scope ``account_id`` (``None``: Total): the ``amount`` itself, or for FIRE the
    ``yearly_expenses`` over the ``withdrawal_rate`` (percent); an optional ``target_date``, and the forecast's
    assumptions: the ``real_return`` (percent a year) and the ``monthly_deposit`` (``None``: the scope's average)."""

    account_id: int | None
    mode: GoalMode
    amount: Decimal | None = None
    yearly_expenses: Decimal | None = None
    withdrawal_rate: Decimal = DEFAULT_WITHDRAWAL_RATE
    target_date: date | None = None
    real_return: Decimal = DEFAULT_REAL_RETURN
    monthly_deposit: Decimal | None = None

    def __post_init__(self) -> None:
        if self.mode is GoalMode.AMOUNT and (self.amount is None or self.amount <= 0):
            raise GoalError("Podaj kwotę celu większą od zera.")
        if self.mode is GoalMode.FIRE:
            if self.yearly_expenses is None or self.yearly_expenses <= 0:
                raise GoalError("Podaj roczne wydatki większe od zera.")
            if not 0 < self.withdrawal_rate < 100:
                raise GoalError("Stopa wypłaty musi być większa od 0 % i mniejsza od 100 %.")
        if self.real_return <= -100:
            raise GoalError("Stopa zwrotu musi być większa od -100 %.")

    @property
    def target(self) -> Decimal:
        """The value in PLN the goal aims at."""
        if self.mode is GoalMode.FIRE:
            assert self.yearly_expenses is not None
            return self.yearly_expenses * 100 / self.withdrawal_rate
        assert self.amount is not None
        return self.amount


@dataclass(frozen=True)
class GoalForecast:
    """Where a goal stands at ``value``: ``progress`` (a fraction of the target), whether it is ``reached``, the
    month it is forecast to be (``reached_on``, ``None`` when reached or out of reach within ``FORECAST_MONTHS``)
    and, with a target date ahead, the ``required_monthly`` deposit to reach it then."""

    target: Decimal
    progress: Decimal
    reached: bool
    reached_on: date | None
    required_monthly: Decimal | None


@dataclass(frozen=True)
class GoalTexts:
    """The goal dialog's fields as typed; the mode decides which of the amount and the FIRE fields count."""

    amount: str = ""
    yearly_expenses: str = ""
    withdrawal_rate: str = format_number(DEFAULT_WITHDRAWAL_RATE, decimals=0)
    target_date: str = ""
    real_return: str = format_number(DEFAULT_REAL_RETURN, decimals=0)
    monthly_deposit: str = ""

    @classmethod
    def of(cls, goal: InvestmentGoal) -> GoalTexts:
        """The texts that read back into ``goal``, for editing it."""

        def text(value: Decimal | None) -> str:
            return "" if value is None else format_exact(value)

        return cls(
            amount=text(goal.amount),
            yearly_expenses=text(goal.yearly_expenses),
            withdrawal_rate=format_exact(goal.withdrawal_rate),
            target_date="" if goal.target_date is None else format_date(goal.target_date),
            real_return=format_exact(goal.real_return),
            monthly_deposit=text(goal.monthly_deposit),
        )


def parse_goal(account_id: int | None, mode: GoalMode, texts: GoalTexts) -> InvestmentGoal:
    """The goal of the View Scope ``account_id`` the dialog's ``texts`` give in ``mode``; raises ``GoalError``
    naming the field that does not read."""

    def number(text: str, message: str) -> Decimal:
        try:
            return parse_number(text)
        except ValueError:
            raise GoalError(message) from None

    def optional(text: str, message: str) -> Decimal | None:
        return None if not text.strip() else number(text, message)

    target_date = None
    if texts.target_date.strip():
        try:
            target_date = parse_date(texts.target_date)
        except ValueError:
            raise GoalError("Data docelowa: wpisz datę jak 31.12.2040.") from None
    fire = mode is GoalMode.FIRE
    return InvestmentGoal(
        account_id=account_id,
        mode=mode,
        amount=None if fire else optional(texts.amount, "Kwota celu: wpisz liczbę, np. 1 000 000."),
        yearly_expenses=optional(texts.yearly_expenses, "Wydatki roczne: wpisz liczbę, np. 60 000.") if fire else None,
        withdrawal_rate=number(texts.withdrawal_rate, "Stopa wypłaty: wpisz liczbę, np. 4.")
        if fire
        else DEFAULT_WITHDRAWAL_RATE,
        target_date=target_date,
        real_return=number(texts.real_return, "Stopa zwrotu: wpisz liczbę, np. 4."),
        monthly_deposit=optional(texts.monthly_deposit, "Miesięczna wpłata: wpisz liczbę albo zostaw puste."),
    )


def average_monthly_deposits(history: Sequence[DayValue], account_id: int | None, today: date) -> Decimal:
    """The View Scope's Net Deposits per month over the ``AVERAGE_MONTHS`` before ``today``, or over the shorter
    History there is (at least a month); nothing without History."""
    if not history:
        return Decimal(0)

    def net_deposits(day: DayValue) -> Decimal:
        return day.net_deposits if account_id is None else day.account_net_deposits.get(account_id, Decimal(0))

    start = add_months(today, -AVERAGE_MONTHS)
    before = [day for day in history if day.day < start]
    if before:
        base, months = net_deposits(before[-1]), Decimal(AVERAGE_MONTHS)
    else:
        base, months = Decimal(0), max(Decimal((today - history[0].day).days) / DAYS_A_MONTH, Decimal(1))
    return (net_deposits(history[-1]) - base) / months


def forecast(goal: InvestmentGoal, value: Decimal, monthly: Decimal, today: date) -> GoalForecast:
    """The goal at today's ``value`` with ``monthly`` deposited at each month's end."""
    target = goal.target
    rate = (1 + goal.real_return / 100) ** (Decimal(1) / 12) - 1
    reached = value >= target
    reached_on = None
    if not reached:
        projected = value
        for month in range(1, FORECAST_MONTHS + 1):
            projected = projected * (1 + rate) + monthly
            if projected >= target:
                reached_on = add_months(today, month)
                break
    return GoalForecast(
        target=target,
        progress=value / target,
        reached=reached,
        reached_on=reached_on,
        required_monthly=None if goal.target_date is None else _required_monthly(target, value, rate, today, goal),
    )


def _required_monthly(
    target: Decimal, value: Decimal, rate: Decimal, today: date, goal: InvestmentGoal
) -> Decimal | None:
    """The deposit at each month's end that reaches ``target`` by the goal's date; ``None`` once it has passed."""
    assert goal.target_date is not None
    months = (goal.target_date.year - today.year) * 12 + goal.target_date.month - today.month
    if goal.target_date.day < today.day:
        months -= 1
    if months <= 0:
        return None
    growth = (1 + rate) ** months
    if rate == 0:
        needed = (target - value) / months
    else:
        needed = (target - value * growth) * rate / (growth - 1)
    return max(needed, Decimal(0))
