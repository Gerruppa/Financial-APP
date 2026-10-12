"""The Dashboard's totals (issue #72, spec section 5) and allocation (issue #73, with the Multi-asset Splits of
#75), from the Transactions and today's prices and NBP Rates.

Like the sheet's Dashboard, "Gotówka" is the PLN Cash Balance and "Otwarte pozycje" the Positions plus the foreign
cash; a Position without a PLN price counts at cost and adds nothing to the result, as in the Portfolio. Net Deposits
come from History's last day, so they match XIRR (spec 6.1).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account
from financial_app.domain.instruments import Instrument
from financial_app.domain.lots import foreign_cash, open_positions, realized_results
from financial_app.domain.metrics import xirr
from financial_app.domain.portfolio_history import CASH_CLASS, FOREIGN_CASH_CLASS, DayValue
from financial_app.domain.transactions import (
    PLN,
    TransactionDraft,
    cash_balances,
    costs_by_account,
    dividends_by_account,
)


@dataclass(frozen=True)
class Totals:
    """Sums in PLN; ``net_deposits`` is ``None`` while History is not computed, ``xirr`` (a fraction) also without a
    rate that settles the flows."""

    net_deposits: Decimal | None
    cash: Decimal
    open_positions: Decimal
    unrealized: Decimal
    realized: Decimal
    dividends: Decimal
    costs: Decimal
    xirr: Decimal | None = None

    @property
    def value(self) -> Decimal:
        return self.cash + self.open_positions


@dataclass(frozen=True)
class AccountRow:
    """An Account's line in the Dashboard's Account table."""

    account: Account
    totals: Totals


@dataclass(frozen=True)
class CurrencyShare:
    """The PLN value held in one currency and its ``share`` of the View Scope's value (a fraction, not percent)."""

    currency: str
    value: Decimal
    share: Decimal


@dataclass(frozen=True)
class ClassShare:
    """The PLN value held in one Asset Class (PLN and foreign cash in classes of their own) and its ``share``."""

    asset_class: str
    value: Decimal
    share: Decimal


@dataclass(frozen=True)
class Dashboard:
    """The sums of the View Scope, a row per Account in it (an inactive one only while it holds something), its
    currency exposure and its allocation by Asset Class, largest first."""

    totals: Totals
    accounts: tuple[AccountRow, ...]
    currencies: tuple[CurrencyShare, ...]
    classes: tuple[ClassShare, ...] = ()


def dashboard(
    transactions: Sequence[TransactionDraft],
    accounts: Sequence[Account],
    instruments: Mapping[int, Instrument],
    prices: Mapping[int, Decimal | None],
    rates: Mapping[str, Decimal],
    history: Sequence[DayValue] | None,
    account_id: int | None = None,
    period: tuple[date, date] | None = None,
) -> Dashboard:
    """The Dashboard of ``transactions`` (in entry order) with Positions at ``prices`` (PLN per unit by Instrument id)
    and foreign cash at ``rates`` (PLN per unit by currency, valued at cost without one).

    ``history`` is History up to today, ``None`` while it is computed; ``account_id`` is the View Scope (an Account, or
    ``None`` for Total) and ``period`` the "from" and "to" days of XIRR. Like the sheet, XIRR ends at today's value as
    the Dashboard shows it (with Manual Prices), not as History has it.
    """
    positions = open_positions(transactions)
    foreign = foreign_cash(transactions)
    balances = cash_balances(transactions)
    realized = realized_results(transactions)
    dividends = dividends_by_account(transactions)
    costs = costs_by_account(transactions)
    last_day = history[-1] if history else None
    rows = []
    exposure: dict[str, Decimal] = {}
    allocation: dict[str, Decimal] = {}

    def count_held(currency: str, amount: Decimal, parts: Iterable[tuple[str, Decimal]]) -> Decimal:
        """Add ``amount`` held in ``currency`` to the exposure and its ``parts`` by Asset Class to the allocation and
        return it."""
        exposure[currency] = exposure.get(currency, Decimal(0)) + amount
        for name, part in parts:
            allocation[name] = allocation.get(name, Decimal(0)) + part
        return amount

    def count_cash(currency: str, asset_class: str, amount: Decimal) -> Decimal:
        return count_held(currency, amount, [(asset_class, amount)])

    for account in (a for a in accounts if account_id in (None, a.id)):
        positions_value = Decimal(0)
        unrealized = Decimal(0)
        account_realized = realized.get(account.id, Decimal(0))
        for position in (p for p in positions if p.account_id == account.id):
            price = prices.get(position.instrument_id)
            instrument = instruments[position.instrument_id]
            value = position.value_or_cost(price)
            positions_value += count_held(instrument.quote_currency, value, instrument.class_parts(value))
            if price is not None:
                unrealized += position.result(price)
        for balance in (c for c in foreign if c.account_id == account.id):
            if not account.exclude_fx_result:
                account_realized += balance.realized_result
            rate = rates.get(balance.currency)
            if rate is None:
                positions_value += count_cash(balance.currency, FOREIGN_CASH_CLASS, balance.cost)
                continue
            positions_value += count_cash(balance.currency, FOREIGN_CASH_CLASS, balance.value(rate))
            if not account.exclude_fx_result:
                unrealized += balance.result(rate)
        count_cash(PLN, CASH_CLASS, balances.get(account.id, Decimal(0)))
        rows.append(
            AccountRow(
                account,
                Totals(
                    net_deposits=None
                    if last_day is None
                    else last_day.account_net_deposits.get(account.id, Decimal(0)),
                    cash=balances.get(account.id, Decimal(0)),
                    open_positions=positions_value,
                    unrealized=unrealized,
                    realized=account_realized,
                    dividends=dividends.get(account.id, Decimal(0)),
                    costs=costs.get(account.id, Decimal(0)),
                ),
            )
        )
    scoped = [row.totals for row in rows]
    if last_day is None:
        net_deposits = None
    else:
        net_deposits = last_day.net_deposits if account_id is None else scoped[0].net_deposits
    xirr_rate = None
    if history and period is not None:
        # Today's values as the Dashboard has them; an Account outside the scope keeps History's
        values = dict(history[-1].accounts) | {row.account.id: row.totals.value for row in rows}
        ending = [*history[:-1], replace(history[-1], accounts=values)]
        xirr_rate = xirr(ending, *period, account_id)
        rows = [replace(row, totals=replace(row.totals, xirr=xirr(ending, *period, row.account.id))) for row in rows]
    totals = Totals(
        net_deposits=net_deposits,
        cash=sum((row.cash for row in scoped), Decimal(0)),
        open_positions=sum((row.open_positions for row in scoped), Decimal(0)),
        unrealized=sum((row.unrealized for row in scoped), Decimal(0)),
        realized=sum((row.realized for row in scoped), Decimal(0)),
        dividends=sum((row.dividends for row in scoped), Decimal(0)),
        costs=sum((row.costs for row in scoped), Decimal(0)),
        xirr=xirr_rate,
    )
    currencies = tuple(CurrencyShare(*share) for share in _shares(exposure))
    classes = tuple(ClassShare(*share) for share in _shares(allocation) if share[1])
    # An inactive Account stays in the totals (its past costs and Dividends) but leaves the table once emptied
    shown = tuple(row for row in rows if row.account.active or row.totals.value or row.account.id == account_id)
    return Dashboard(totals, shown, currencies, classes)


def _shares(values: Mapping[str, Decimal]) -> list[tuple[str, Decimal, Decimal]]:
    """Each name with its value and share of their sum, largest first."""
    total = sum(values.values(), Decimal(0))
    return [
        (name, amount, amount / total if total else Decimal(0))
        for name, amount in sorted(values.items(), key=lambda item: item[1], reverse=True)
    ]
