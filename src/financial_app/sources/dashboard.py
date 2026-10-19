"""Today's Dashboard of a View Scope (issues #72 and #76) from ``sources.todays_view``, shared by the Dashboard and
the Investment Strategy."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Engine

from financial_app.domain.accounts import Account
from financial_app.domain.dashboard import Dashboard, dashboard
from financial_app.domain.instruments import Instrument
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.transactions import TransactionDraft
from financial_app.sources.current_prices import LatestRates
from financial_app.sources.todays_view import todays_view


@dataclass(frozen=True)
class TodaysDashboard:
    """The Dashboard of a View Scope with what it was computed from."""

    board: Dashboard
    transactions: Sequence[TransactionDraft]
    accounts: list[Account]
    instruments: dict[int, Instrument]


def todays_dashboard(
    engine: Engine,
    rates: LatestRates,
    account_id: int | None,
    days: list[DayValue] | None = None,
    period: tuple[date, date] | None = None,
) -> TodaysDashboard:
    """The Dashboard of the Account ``account_id`` (``None``: Total) at today's prices and NBP Rates; ``days`` is
    History (``None`` while it is computed) and ``period`` the days XIRR runs over."""
    view = todays_view(engine, rates)
    board = dashboard(
        view.transactions,
        view.accounts,
        view.instruments,
        view.pln_prices,
        view.rates,
        days,
        account_id,
        period,
        view.accrued,
    )
    return TodaysDashboard(board, view.transactions, view.accounts, view.instruments)
