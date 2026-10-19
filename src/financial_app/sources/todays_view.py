"""Today's state of the portfolio, loaded once for the tabs to draw (issue #109): the Transactions in entry order, the
Accounts, Instruments, Positions and Cash Balances, and the held Instruments' prices and the NBP Rates of today.

The Portfolio, the Dashboard (through ``sources.dashboard``), Multi-asset and Obligacje read it, so the FIFO replay,
the prices and the value of an Account are the same on each of them."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import cached_property

from sqlalchemy import Engine

from financial_app.domain.account_value import AccountValue, account_value
from financial_app.domain.accounts import Account
from financial_app.domain.bond_valuation import BondData
from financial_app.domain.instruments import Instrument
from financial_app.domain.lots import ForeignCash, Position, UnitPrice, foreign_cash, open_positions
from financial_app.domain.term_deposits import Accruals, AccruedInterest, TermDeposit, tax_rates_of
from financial_app.domain.transactions import Transaction, cash_balances
from financial_app.domain.valuation import InstrumentPrice
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.bond_series import load_bond_data
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.term_deposits import list_deposits
from financial_app.persistence.transactions import transactions_in_entry_order
from financial_app.sources.current_prices import LatestRates, TodaysRates, current_prices
from financial_app.sources.prices import last_refresh


@dataclass(frozen=True)
class TodaysView:
    """Every Account's state on ``today``: ``transactions`` in entry order, the open ``positions``, the ``foreign``
    cash and the PLN ``cash`` per Account id; ``prices`` of each held Instrument by id and the NBP ``rates`` found by
    currency (each held Instrument's and each Transaction's cash currency asked for); ``bonds`` values Bond Series;
    ``deposits`` are the Term Deposits and ``accrued`` their interest earned by today, by Account id (issue #160)."""

    today: date
    transactions: list[Transaction]
    accounts: list[Account]
    instruments: dict[int, Instrument]
    positions: list[Position]
    foreign: list[ForeignCash]
    cash: dict[int, Decimal]
    prices: dict[int, InstrumentPrice]
    rates: dict[str, Decimal]
    bonds: BondData
    deposits: list[TermDeposit]
    accrued: dict[int, AccruedInterest]

    @cached_property
    def pln_prices(self) -> dict[int, UnitPrice | None]:
        """Each held Instrument's PLN price per unit, ``None`` without one."""
        return {instrument_id: price.pln for instrument_id, price in self.prices.items()}

    def account_value(self, account: Account) -> AccountValue:
        """The Account's value and result today (``domain.account_value``)."""
        return account_value(
            account,
            self.cash.get(account.id, Decimal(0)),
            self.positions,
            self.foreign,
            self.pln_prices,
            self.rates,
            self.accrued.get(account.id, AccruedInterest()).net,
        )


def todays_view(engine: Engine, rates: LatestRates) -> TodaysView:
    """Load today's state from the database, with today's NBP Rates from ``rates``, each currency asked once."""
    transactions = transactions_in_entry_order(engine)
    instruments = {i.id: i for i in list_instruments(engine)}
    positions = open_positions(transactions)
    todays_rates = TodaysRates(rates)
    held_ids = {p.instrument_id for p in positions}
    held = [instrument for instrument in instruments.values() if instrument.id in held_ids]
    bonds = load_bond_data(engine)
    prices = current_prices(engine, held, todays_rates, last_refresh(engine), bonds)
    for currency in {t.cash_currency for t in transactions}:
        todays_rates(currency)
    today = todays_rates.today()
    accounts = list_accounts(engine)
    deposits = list_deposits(engine)
    return TodaysView(
        today=today,
        transactions=transactions,
        accounts=accounts,
        instruments=instruments,
        positions=positions,
        foreign=foreign_cash(transactions),
        cash=cash_balances(transactions),
        prices=prices,
        rates=todays_rates.known(),
        bonds=bonds,
        deposits=deposits,
        accrued=Accruals(deposits, tax_rates_of(accounts), transactions).on(today),
    )
