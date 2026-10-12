"""Today's Dashboard of a View Scope from the database (issues #72 and #76): the Transactions, today's prices
(``sources.current_prices``) and NBP Rates, shared by the Dashboard and the Investment Strategy."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Engine

from financial_app.domain.accounts import Account
from financial_app.domain.dashboard import Dashboard, dashboard
from financial_app.domain.instruments import Instrument
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.transactions import TransactionDraft
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import list_transactions
from financial_app.sources.current_prices import TodaysRates, current_prices
from financial_app.sources.nbp import NbpRates
from financial_app.sources.prices import last_refresh


@dataclass(frozen=True)
class TodaysDashboard:
    """The Dashboard of a View Scope with what it was computed from."""

    board: Dashboard
    transactions: Sequence[TransactionDraft]
    accounts: list[Account]
    instruments: dict[int, Instrument]


def todays_dashboard(
    engine: Engine,
    rates: NbpRates,
    account_id: int | None,
    days: list[DayValue] | None = None,
    period: tuple[date, date] | None = None,
) -> TodaysDashboard:
    """The Dashboard of the Account ``account_id`` (``None``: Total) at today's prices and NBP Rates; ``days`` is
    History (``None`` while it is computed) and ``period`` the days XIRR runs over."""
    # list_transactions is newest first; the FIFO engine wants entry order
    transactions = list(reversed(list_transactions(engine)))
    instruments = {i.id: i for i in list_instruments(engine)}
    todays_rates = TodaysRates(rates)
    prices = {
        i: price.pln
        for i, price in current_prices(engine, instruments.values(), todays_rates, last_refresh(engine)).items()
    }
    for currency in {t.cash_currency for t in transactions}:
        todays_rates(currency)
    accounts = list_accounts(engine)
    board = dashboard(transactions, accounts, instruments, prices, todays_rates.known(), days, account_id, period)
    return TodaysDashboard(board, transactions, accounts, instruments)
