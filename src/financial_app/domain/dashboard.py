"""The Dashboard's totals (issue #72, spec section 5), allocation (issue #73, with the Multi-asset Splits of #75),
the Account ranking's figures and the profit by source (issue #89), from the Transactions and today's prices and NBP
Rates.

Like the sheet's Dashboard, "Gotówka" is the PLN Cash Balance and "Otwarte pozycje" the Positions plus the foreign
cash; a Position without a PLN price counts at cost and adds nothing to the result, as in the Portfolio. Net Deposits
come from History's last day, so they match XIRR (spec 6.1).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from financial_app.domain.account_value import account_value, is_listed
from financial_app.domain.accounts import Account, tax_regime_for
from financial_app.domain.bond_redemption import net_value
from financial_app.domain.bond_valuation import BondPrice
from financial_app.domain.instruments import Instrument
from financial_app.domain.lots import Position, UnitPrice, foreign_cash, replay
from financial_app.domain.metrics import twr, xirr
from financial_app.domain.portfolio_history import CASH_CLASS, FOREIGN_CASH_CLASS, DayValue
from financial_app.domain.profit_sources import ProfitSources, profit_sources
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
    rate that settles the flows, ``twr`` (a fraction) without a period. ``estimated_tax`` is the Belka a Regular
    Account would pay on its unrealised gains at the Tax cost if it sold everything today (issue #89), plus what
    redeeming its Bond Series today would cost: the early-redemption fee and the tax withheld (spec 3.4.1)."""

    net_deposits: Decimal | None
    cash: Decimal
    open_positions: Decimal
    unrealized: Decimal
    realized: Decimal
    dividends: Decimal
    costs: Decimal
    xirr: Decimal | None = None
    twr: Decimal | None = None
    estimated_tax: Decimal = Decimal(0)

    @property
    def value(self) -> Decimal:
        return self.cash + self.open_positions

    @property
    def profit(self) -> Decimal | None:
        """The value less the Net Deposits, as the sheet's "Zysk / strata"; ``None`` while History is computed."""
        return None if self.net_deposits is None else self.value - self.net_deposits

    def unrealized_after(self, after_tax: bool) -> Decimal:
        """The unrealised result, less the estimated tax when ``after_tax``."""
        return self.unrealized - self.estimated_tax if after_tax else self.unrealized

    def profit_after(self, after_tax: bool) -> Decimal | None:
        """The P&L, less the estimated tax when ``after_tax``."""
        if self.profit is None:
            return None
        return self.profit - self.estimated_tax if after_tax else self.profit


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
    currency exposure and its allocation by Asset Class, largest first. For the Investment Strategy (issue #76),
    ``holdings`` is the value by Asset Class name and Instrument id and ``account_classes`` each Account's value by
    Asset Class name, cash included; ``sources`` is the scope's result by source (issue #89)."""

    totals: Totals
    accounts: tuple[AccountRow, ...]
    currencies: tuple[CurrencyShare, ...]
    classes: tuple[ClassShare, ...] = ()
    holdings: Mapping[str, Mapping[int, Decimal]] = field(default_factory=dict)
    account_classes: Mapping[int, Mapping[str, Decimal]] = field(default_factory=dict)
    sources: ProfitSources = ProfitSources()


def dashboard(
    transactions: Sequence[TransactionDraft],
    accounts: Sequence[Account],
    instruments: Mapping[int, Instrument],
    prices: Mapping[int, UnitPrice | None],
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
    moves = replay(transactions)
    foreign = foreign_cash(transactions)
    balances = cash_balances(transactions)
    dividends = dividends_by_account(transactions)
    costs = costs_by_account(transactions)
    last_day = history[-1] if history else None
    rows = []
    exposure: dict[str, Decimal] = {}
    allocation: dict[str, Decimal] = {}
    holdings: dict[str, dict[int, Decimal]] = {}
    account_classes: dict[int, dict[str, Decimal]] = {}
    # Unrealised gains at the Tax cost by tax rate: PIT-38 is one return, so Total offsets the Accounts' gains
    taxable: dict[Decimal, Decimal] = {}
    withheld_total = Decimal(0)
    listed: set[int] = set()
    # The FX part of the scope's unrealised and realised result, for the profit by source
    fx = Decimal(0)

    def count_held(
        currency: str, amount: Decimal, parts: Iterable[tuple[str, Decimal]], instrument_id: int | None = None
    ) -> None:
        """Add ``amount`` held in ``currency`` to the exposure and its ``parts`` by Asset Class to the allocation (of
        the scope and of the Account) and to the holdings of ``instrument_id``."""
        exposure[currency] = exposure.get(currency, Decimal(0)) + amount
        by_class = account_classes.setdefault(account.id, {})
        for name, part in parts:
            allocation[name] = allocation.get(name, Decimal(0)) + part
            by_class[name] = by_class.get(name, Decimal(0)) + part
            if instrument_id is not None:
                held = holdings.setdefault(name, {})
                held[instrument_id] = held.get(instrument_id, Decimal(0)) + part

    def count_cash(currency: str, asset_class: str, amount: Decimal) -> None:
        count_held(currency, amount, [(asset_class, amount)])

    for account in (a for a in accounts if account_id in (None, a.id)):
        held_value = account_value(
            account, balances.get(account.id, Decimal(0)), moves.positions, foreign, prices, rates
        )
        if is_listed(account, held_value) or account.id == account_id:
            listed.add(account.id)
        taxable_gain = Decimal(0)
        # A Bond Series' early-redemption fee and the tax withheld at redemption, outside PIT-38 (spec 3.4.1)
        withheld = Decimal(0)
        fx += moves.realized_fx.get(account.id, Decimal(0))
        if not account.exclude_fx_result:
            fx += held_value.fx
        for position in (p for p in moves.positions if p.account_id == account.id):
            price = prices.get(position.instrument_id)
            instrument = instruments[position.instrument_id]
            value = position.value_or_cost(price)
            count_held(instrument.quote_currency, value, instrument.class_parts(value), position.instrument_id)
            if isinstance(price, BondPrice):
                withheld += _bond_deductions(position, price, account)
            elif price is not None:
                taxable_gain += position.value(price) - position.tax_cost
            if price is not None and (rate := rates.get(instrument.quote_currency)) is not None:
                fx += position.fx_result(rate)
        for balance in (c for c in foreign if c.account_id == account.id):
            rate = rates.get(balance.currency)
            count_cash(balance.currency, FOREIGN_CASH_CLASS, balance.cost if rate is None else balance.value(rate))
        count_cash(PLN, CASH_CLASS, held_value.cash)
        tax_rate = tax_regime_for(account.account_type).unrealized_tax_rate
        taxable[tax_rate] = taxable.get(tax_rate, Decimal(0)) + taxable_gain
        withheld_total += withheld
        rows.append(
            AccountRow(
                account,
                Totals(
                    net_deposits=None
                    if last_day is None
                    else last_day.account_net_deposits.get(account.id, Decimal(0)),
                    cash=held_value.cash,
                    open_positions=held_value.open_positions,
                    unrealized=held_value.unrealized,
                    realized=moves.realized.get(account.id, Decimal(0)) + held_value.realized_fx,
                    dividends=dividends.get(account.id, Decimal(0)),
                    costs=costs.get(account.id, Decimal(0)),
                    estimated_tax=_estimated_tax(tax_rate, taxable_gain) + withheld,
                ),
            )
        )
    scoped = [row.totals for row in rows]
    if last_day is None:
        net_deposits = None
    else:
        net_deposits = last_day.net_deposits if account_id is None else scoped[0].net_deposits
    xirr_rate = twr_rate = None
    if history and period is not None:
        # Today's values as the Dashboard has them; an Account outside the scope keeps History's
        values = dict(history[-1].accounts) | {row.account.id: row.totals.value for row in rows}
        ending = [*history[:-1], replace(history[-1], accounts=values)]
        xirr_rate = xirr(ending, *period, account_id)
        twr_rate = twr(ending, *period, account_id)
        rows = [
            replace(
                row,
                totals=replace(
                    row.totals, xirr=xirr(ending, *period, row.account.id), twr=twr(ending, *period, row.account.id)
                ),
            )
            for row in rows
        ]
    totals = Totals(
        net_deposits=net_deposits,
        cash=sum((row.cash for row in scoped), Decimal(0)),
        open_positions=sum((row.open_positions for row in scoped), Decimal(0)),
        unrealized=sum((row.unrealized for row in scoped), Decimal(0)),
        realized=sum((row.realized for row in scoped), Decimal(0)),
        dividends=sum((row.dividends for row in scoped), Decimal(0)),
        costs=sum((row.costs for row in scoped), Decimal(0)),
        xirr=xirr_rate,
        twr=twr_rate,
        estimated_tax=sum((_estimated_tax(rate, gain) for rate, gain in taxable.items()), withheld_total),
    )
    currencies = tuple(CurrencyShare(*share) for share in _shares(exposure))
    classes = tuple(ClassShare(*share) for share in _shares(allocation) if share[1])
    # An inactive Account stays in the totals (its past costs and Dividends) but leaves the table once emptied
    shown = tuple(row for row in rows if row.account.id in listed)
    held = {account: {name: v for name, v in values.items() if v} for account, values in account_classes.items()}
    return Dashboard(
        totals,
        shown,
        currencies,
        classes,
        holdings,
        {a: values for a, values in held.items() if values},
        profit_sources(transactions, {row.account.id for row in rows}, totals.unrealized + totals.realized, fx),
    )


def _bond_deductions(position: Position, price: BondPrice, account: Account) -> Decimal:
    """What redeeming the Bond Series' Lots today would cost: the early-redemption fee and the tax the Account's Tax
    Regime withholds, i.e. the gross value less the net value of the Obligacje tab."""
    rate = tax_regime_for(account.account_type).withheld_tax_rate
    values = ((lot, net_value(price, lot, rate)) for lot in position.lots)
    return sum((lot.quantity * v.deductions for lot, v in values if v is not None), Decimal(0))


def _estimated_tax(rate: Decimal, gain: Decimal) -> Decimal:
    """The tax at ``rate`` on an unrealised ``gain``; nothing on a loss."""
    return rate * max(gain, Decimal(0))


def _shares(values: Mapping[str, Decimal]) -> list[tuple[str, Decimal, Decimal]]:
    """Each name with its value and share of their sum, largest first."""
    total = sum(values.values(), Decimal(0))
    return [
        (name, amount, amount / total if total else Decimal(0))
        for name, amount in sorted(values.items(), key=lambda item: item[1], reverse=True)
    ]
