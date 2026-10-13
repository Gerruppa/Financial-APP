"""The Wyniki tab's figures (issue #74, spec section 5 and 6.1), from History through ``metrics``.

``period_results`` gives the View Scope's results over the chosen period: XIRR, TWR, the deepest drawdown of the TWR
with the days it took to win back, the volatility and the real return, the TWR after the GUS CPI's inflation
(``domain/inflation.py``, L-10). ``results_rows`` gives XIRR and TWR over the fixed periods YTD, 1R, 3L and Od
początku for the Total and each Account (in the Total scope) or for the scope's Account. A period reaching before
History is clipped to it, as everywhere. Returns are fractions, not percent.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account
from financial_app.domain.bonds import CpiReading
from financial_app.domain.inflation import Inflation, inflation, real_return
from financial_app.domain.metrics import MaxDrawdown, max_drawdown, twr, volatility, xirr
from financial_app.domain.periods import Period, PeriodPreset, period_dates
from financial_app.domain.portfolio_history import DayValue

# The fixed periods of the results table (spec section 5)
TABLE_PRESETS = (
    PeriodPreset.YEAR_TO_DATE,
    PeriodPreset.ONE_YEAR,
    PeriodPreset.THREE_YEARS,
    PeriodPreset.SINCE_INCEPTION,
)


@dataclass(frozen=True)
class Returns:
    """The money-weighted (``None`` without a rate) and the time-weighted return over a period."""

    xirr: Decimal | None
    twr: Decimal


@dataclass(frozen=True)
class PeriodResults:
    """A scope's results over a period; ``max_drawdown`` ``None`` when the TWR never fell, ``volatility`` with fewer
    than two weekday returns, ``inflation`` ``None`` when GUS published no month of the period."""

    returns: Returns
    max_drawdown: MaxDrawdown | None
    volatility: Decimal | None
    inflation: Inflation | None = None

    @property
    def xirr(self) -> Decimal | None:
        return self.returns.xirr

    @property
    def twr(self) -> Decimal:
        return self.returns.twr

    @property
    def real_return(self) -> Decimal | None:
        """The TWR after the period's inflation; ``None`` without it."""
        return None if self.inflation is None else real_return(self.twr, self.inflation.rate)

    @property
    def recovery_days(self) -> int | None:
        """Days from the drawdown's trough until the TWR was back at its peak; ``None`` until it is."""
        drawdown = self.max_drawdown
        if drawdown is None or drawdown.recovered_on is None:
            return None
        return (drawdown.recovered_on - drawdown.trough).days


@dataclass(frozen=True)
class ResultsRow:
    """The returns of the Total (``account`` ``None``) or an Account over each of ``TABLE_PRESETS``."""

    account: Account | None
    returns: Mapping[PeriodPreset, Returns]


def period_results(
    history: Sequence[DayValue],
    first: date,
    last: date,
    account_id: int | None = None,
    cpi: Iterable[CpiReading] = (),
) -> PeriodResults:
    """The scope's results from the "from" day ``first`` to ``last``, the real return from the ``cpi`` readings.

    Inflation counts from the day the scope first held something, as the TWR does, so an Account opened within the
    period is not charged the inflation of the days before."""
    held_from = next((day.day for day in history if first <= day.day and _holds(day, account_id)), first)
    return PeriodResults(
        _returns(history, first, last, account_id),
        max_drawdown(history, first, last, account_id),
        volatility(history, first, last, account_id),
        inflation(cpi, held_from, last),
    )


def results_rows(
    history: Sequence[DayValue], accounts: Sequence[Account], account_id: int | None, today: date
) -> list[ResultsRow]:
    """In the Total scope the Total, then each Account with something in History, highest value today first (an
    inactive one only while it holds something, as in the Dashboard's table); in an Account scope that Account alone.
    No History, no rows."""
    if not history:
        return []
    inception = history[0].day
    periods = {preset: period_dates(Period(preset), today, inception) for preset in TABLE_PRESETS}

    def row(account: Account | None) -> ResultsRow:
        scope = None if account is None else account.id
        returns = {preset: _returns(history, first, last, scope) for preset, (first, last) in periods.items()}
        return ResultsRow(account, returns)

    if account_id is not None:
        return [row(account) for account in accounts if account.id == account_id]
    latest = history[-1].accounts
    held = [
        account
        for account in accounts
        if (account.active or latest.get(account.id)) and any(_holds(day, account.id) for day in history)
    ]
    held.sort(key=lambda account: (-latest.get(account.id, Decimal(0)), account.name.casefold()))
    return [row(None), *(row(account) for account in held)]


def _returns(history: Sequence[DayValue], first: date, last: date, account_id: int | None) -> Returns:
    return Returns(xirr(history, first, last, account_id), twr(history, first, last, account_id))


def _holds(day: DayValue, account_id: int | None) -> bool:
    """Whether the Account (the Total for ``None``) holds something or has Net Deposits at the end of ``day``."""
    if account_id is None:
        return bool(day.total or day.net_deposits)
    return bool(day.accounts.get(account_id) or day.account_net_deposits.get(account_id))
