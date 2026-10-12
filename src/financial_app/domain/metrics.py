"""Metrics on History (spec 6.1): XIRR, TWR, drawdown, volatility and the daily change of the Total or one Account.

Each takes the History (``portfolio_history.daily_history``), a period from ``first`` to ``last`` and the scope:
``account_id`` ``None`` for the Total, whose flows are Deposits and Withdrawals, or an Account, whose flows also count
Cash and Security Transfers. A day's flow is the change in its Net Deposits and comes at the end of the day. A period
reaching before the History is clipped to it. Returns are fractions (0.05 is 5 %).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financial_app.domain.portfolio_history import DayValue

# An XIRR above it is taken as no rate (10 ** 6 % a year)
_HIGHEST_RATE = 1e4
# Weekdays a year, annualising the volatility of daily returns
_TRADING_DAYS = 252


@dataclass(frozen=True)
class _Day:
    day: date
    value: Decimal
    flow: Decimal


@dataclass(frozen=True)
class _Period:
    """The "from" day and the days after it; no "from" day when the period starts with the History, from nothing."""

    start: _Day | None
    days: list[_Day]

    @property
    def start_value(self) -> Decimal:
        return Decimal(0) if self.start is None else self.start.value


@dataclass(frozen=True)
class MaxDrawdown:
    """The deepest fall of the TWR in a period: from its ``peak`` to its ``trough``, won back on ``recovered_on``."""

    depth: Decimal
    peak: date
    trough: date
    recovered_on: date | None


def twr(history: Sequence[DayValue], first: date, last: date, account_id: int | None = None) -> Decimal:
    """The time-weighted return: the daily returns (V_D − F_D) / V_{D−1} − 1 chained over the period."""
    growth = Decimal(1)
    for _, rate in _daily_returns(_period(history, first, last, account_id)):
        growth *= 1 + rate
    return growth - 1


def xirr(history: Sequence[DayValue], first: date, last: date, account_id: int | None = None) -> Decimal | None:
    """The money-weighted annual return: the value on the "from" day and each flow paid in, the "to" value paid out.

    ``None`` when no rate settles them, e.g. with nothing invested.
    """
    period = _period(history, first, last, account_id)
    if not period.days:
        return None
    end = period.days[-1]
    flows = [] if period.start is None else [(period.start.day, -period.start.value)]
    flows += [(day.day, -day.flow) for day in period.days]
    flows.append((end.day, end.value))
    # (Years before the end, amount): compounding forward keeps every power at most (1 + rate) ** length
    timed = [((end.day - day).days / 365, float(amount)) for day, amount in flows if amount]
    if len({years for years, _ in timed}) < 2 or not (
        any(amount < 0 for _, amount in timed) and any(amount > 0 for _, amount in timed)
    ):
        return None

    # A rate, unlike an amount, is solved in float: the bisection takes hundreds of fractional powers
    def future_value(rate: float) -> float:
        return sum(amount * math.exp(years * math.log1p(rate)) for years, amount in timed)

    low, high = -1 + 1e-12, 1.0
    while future_value(high) * future_value(low) > 0:
        if high >= _HIGHEST_RATE:
            return None
        high *= 10
    for _ in range(200):
        middle = (low + high) / 2
        if future_value(middle) * future_value(low) > 0:
            low = middle
        else:
            high = middle
    rate = Decimal(f"{(low + high) / 2:.10f}")
    return rate.copy_abs() if rate.is_zero() else rate


def drawdowns(
    history: Sequence[DayValue], first: date, last: date, account_id: int | None = None
) -> list[tuple[date, Decimal]]:
    """Each day's fall of the TWR below its highest point so far in the period (0 or negative)."""
    points = []
    highest = Decimal(1)
    for day, growth in _growth(_period(history, first, last, account_id)):
        highest = max(highest, growth)
        points.append((day, growth / highest - 1))
    return points


def max_drawdown(
    history: Sequence[DayValue], first: date, last: date, account_id: int | None = None
) -> MaxDrawdown | None:
    """The deepest drawdown in the period, ``None`` when the TWR never fell."""
    points = _growth(_period(history, first, last, account_id))
    deepest: MaxDrawdown | None = None
    peak_day, peak_growth = None, Decimal(0)
    for day, growth in points:
        if peak_day is None or growth >= peak_growth:
            peak_day, peak_growth = day, growth
        depth = growth / peak_growth - 1
        if depth < 0 and (deepest is None or depth < deepest.depth):
            recovered = next((later for later, then in points if later > day and then >= peak_growth), None)
            deepest = MaxDrawdown(depth, peak_day, day, recovered)
    return deepest


def volatility(history: Sequence[DayValue], first: date, last: date, account_id: int | None = None) -> Decimal | None:
    """The annualised volatility: the sample standard deviation of the weekday (Mon–Fri) TWR returns times √252.

    ``None`` with fewer than two such returns.
    """
    returns = [rate for day, rate in _daily_returns(_period(history, first, last, account_id)) if day.weekday() < 5]
    if len(returns) < 2:
        return None
    mean = sum(returns, Decimal(0)) / len(returns)
    variance = sum(((rate - mean) ** 2 for rate in returns), Decimal(0)) / (len(returns) - 1)
    return (variance * _TRADING_DAYS).sqrt()


def daily_change(history: Sequence[DayValue], account_id: int | None = None) -> Decimal | None:
    """The last day's change: its value less the day before's and less its flows (spec 6.1); ``None`` without days."""
    days = _scope_days(history, account_id)
    if not days:
        return None
    previous = days[-2].value if len(days) > 1 else Decimal(0)
    return days[-1].value - previous - days[-1].flow


def _growth(period: _Period) -> list[tuple[date, Decimal]]:
    """The TWR index, 1 on the "from" day, then on each day after it."""
    returns = dict(_daily_returns(period))
    growth = Decimal(1)
    points = [] if period.start is None else [(period.start.day, growth)]
    for day in period.days:
        growth *= 1 + returns.get(day.day, Decimal(0))
        points.append((day.day, growth))
    return points


def _daily_returns(period: _Period) -> list[tuple[date, Decimal]]:
    """Each day's return; a day after one with nothing invested has none."""
    returns = []
    previous = period.start_value
    for day in period.days:
        if previous != 0:
            returns.append((day.day, (day.value - day.flow) / previous - 1))
        previous = day.value
    return returns


def _period(history: Sequence[DayValue], first: date, last: date, account_id: int | None) -> _Period:
    days = _scope_days(history, account_id)
    within = [day for day in days if day.day <= last]
    if not within or first <= within[0].day:
        return _Period(None, within)
    start = [day for day in within if day.day <= first][-1]
    return _Period(start, [day for day in within if day.day > first])


def _scope_days(history: Sequence[DayValue], account_id: int | None) -> list[_Day]:
    days = []
    deposits_before = Decimal(0)
    for day_value in history:
        if account_id is None:
            value, deposits = day_value.total, day_value.net_deposits
        else:
            value = day_value.accounts.get(account_id, Decimal(0))
            deposits = day_value.account_net_deposits.get(account_id, Decimal(0))
        days.append(_Day(day_value.day, value, deposits - deposits_before))
        deposits_before = deposits
    return days
