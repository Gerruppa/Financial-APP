"""The Wyniki tab's figures (issue #74, spec section 5 and 6.1), from History through ``metrics``.

``period_results`` gives the View Scope's results over the chosen period: XIRR, TWR, the deepest drawdown of the TWR
with the days it took to win back, and the volatility. ``results_rows`` gives XIRR and TWR over the fixed periods YTD,
1R, 3L and Od początku for the Total and each Account (in the Total scope) or for the scope's Account. A period
reaching before History is clipped to it, as everywhere. Returns are fractions, not percent.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account
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
    than two weekday returns."""

    returns: Returns
    max_drawdown: MaxDrawdown | None
    volatility: Decimal | None

    @property
    def xirr(self) -> Decimal | None:
        return self.returns.xirr

    @property
    def twr(self) -> Decimal:
        return self.returns.twr

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
    history: Sequence[DayValue], first: date, last: date, account_id: int | None = None
) -> PeriodResults:
    """The scope's results from the "from" day ``first`` to ``last``."""
    return PeriodResults(
        _returns(history, first, last, account_id),
        max_drawdown(history, first, last, account_id),
        volatility(history, first, last, account_id),
    )


def results_rows(
    history: Sequence[DayValue], accounts: Sequence[Account], account_id: int | None, today: date
) -> list[ResultsRow]:
    """In the Total scope the Total, then each Account with something in History, highest value today first; in an
    Account scope that Account alone. No History, no rows."""
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
    held = [account for account in accounts if any(_holds(day, account.id) for day in history)]
    latest = history[-1].accounts
    held.sort(key=lambda account: (-latest.get(account.id, Decimal(0)), account.name.casefold()))
    return [row(None), *(row(account) for account in held)]


def _returns(history: Sequence[DayValue], first: date, last: date, account_id: int | None) -> Returns:
    return Returns(xirr(history, first, last, account_id), twr(history, first, last, account_id))


def _holds(day: DayValue, account_id: int) -> bool:
    return bool(day.accounts.get(account_id) or day.account_net_deposits.get(account_id))
