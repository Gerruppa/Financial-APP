"""History: the Portfolio's value on each day, per Account and Asset Class, and its Net Deposits (spec 6.1, ADR-0002).

Recomputed from the Transactions and the cached daily prices and NBP Rates, never stored. Positions come from the
single FIFO engine (ADR-0003) replayed up to each day. A day without a price carries the last one forward; with none
on or before it, a Position is valued at cost and listed in ``unpriced``. Bond Series are valued at cost until Stage 3.
Foreign prices and cash are converted at the NBP Rate published that day (else the latest earlier), not D-1.

History prices are split-adjusted by their source (ADR-0006), while the Lots hold the units of their day, so a price is
rescaled by the Splits recorded between the day its units refer to and the day it values.
"""

from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from financial_app.domain.currencies import NbpRate
from financial_app.domain.history import ONE_DAY
from financial_app.domain.instruments import Instrument
from financial_app.domain.lots import ForeignCash, Position, foreign_cash, open_positions
from financial_app.domain.prices import STAGE_3_CLASSES
from financial_app.domain.transactions import PLN, SplitRatio, TransactionDraft, TransactionType, cash_balances

# The Asset Classes PLN and foreign cash are counted in
CASH_CLASS = "Gotówka"
FOREIGN_CASH_CLASS = "Waluty"


@dataclass(frozen=True)
class HistoryPrice:
    """An Instrument's price on ``day`` in ``currency``.

    ``adjusted_on`` is the day a split-adjusting source (Yahoo or Stooq history) was asked: the price is in the units
    of that day. ``None`` for a Quote of the price refresh, which is in the units of its own day.
    """

    day: date
    price: Decimal
    currency: str
    adjusted_on: date | None = None

    @property
    def units_of(self) -> date:
        return self.adjusted_on or self.day


@dataclass(frozen=True)
class DayValue:
    """The Portfolio at the end of ``day``, in PLN.

    ``account_net_deposits`` also count Cash and Security Transfers between Accounts, a Security Transfer at the moved
    units' value that day (their cost without a price); ``net_deposits`` only Deposits and Withdrawals. ``unpriced``
    are the Instruments valued at cost that day for want of a price or an NBP Rate, ``unpriced_currencies`` the
    foreign cash valued at cost for want of an NBP Rate. ``account_classes`` splits each Account's value by class, a
    Multi-asset Instrument's by its Multi-asset Split.
    """

    day: date
    accounts: Mapping[int, Decimal]
    classes: Mapping[str, Decimal]
    net_deposits: Decimal
    account_net_deposits: Mapping[int, Decimal]
    unpriced: frozenset[int]
    unpriced_currencies: frozenset[str] = frozenset()
    account_classes: Mapping[int, Mapping[str, Decimal]] = field(default_factory=dict)

    @property
    def total(self) -> Decimal:
        return sum(self.accounts.values(), Decimal(0))


def daily_history(
    transactions: Sequence[TransactionDraft],
    instruments: Mapping[int, Instrument],
    prices: Mapping[int, Sequence[HistoryPrice]],
    rates: Mapping[str, Sequence[NbpRate]],
    first: date,
    last: date,
) -> list[DayValue]:
    """Each day from ``first`` to ``last``.

    ``transactions`` come in entry order (for the FIFO engine's same-day ties), ``prices`` by Instrument id and
    ``rates`` by currency, both oldest first.
    """
    pricing = _Pricing(instruments, prices, rates, _splits(transactions))
    change_days = {t.date for t in transactions}
    flows = _flows(transactions, pricing)
    flows_by_day: dict[date, list[_Flow]] = {}
    for t in transactions:
        flows_by_day.setdefault(max(t.date, first), []).extend(flows.get(id(t), ()))
    history: list[DayValue] = []
    net_deposits, account_net_deposits = Decimal(0), dict[int, Decimal]()
    state: _State | None = None
    day = first
    while day <= last:
        if state is None or day in change_days:
            state = _State.on(transactions, day)
        net_deposits, account_net_deposits = _add_flows(net_deposits, account_net_deposits, flows_by_day.get(day, ()))
        history.append(_value(state, pricing, day, net_deposits, account_net_deposits))
        day += ONE_DAY
    return history


@dataclass(frozen=True)
class _State:
    """The open Positions and Cash Balances at the end of a day."""

    positions: list[Position]
    cash: dict[int, Decimal]
    foreign_cash: list[ForeignCash]

    @staticmethod
    def on(transactions: Sequence[TransactionDraft], day: date) -> _State:
        until = [t for t in transactions if t.date <= day]
        return _State(open_positions(until), cash_balances(until), foreign_cash(until))


class _Pricing:
    def __init__(
        self,
        instruments: Mapping[int, Instrument],
        prices: Mapping[int, Sequence[HistoryPrice]],
        rates: Mapping[str, Sequence[NbpRate]],
        splits: Mapping[int, Sequence[tuple[date, SplitRatio]]],
    ) -> None:
        self.instruments = instruments
        self.prices = prices
        self.price_days = {key: [price.day for price in values] for key, values in prices.items()}
        self.rates = rates
        self.rate_days = {key: [rate.published_on for rate in values] for key, values in rates.items()}
        self.splits = splits

    def unit_pln(self, instrument_id: int, day: date) -> Decimal | None:
        """One unit's PLN value at the end of ``day``, in that day's units; ``None`` without a price or NBP Rate."""
        instrument = self.instruments[instrument_id]
        if self.is_bond(instrument_id):
            return None
        price = _last_on(self.prices.get(instrument_id, ()), self.price_days.get(instrument_id, []), day)
        if price is None:
            return None
        rate = self.rate(price.currency, day)
        if rate is None:
            return None
        return instrument.unit_price(price.price * self._rescaling(instrument_id, price.units_of, day)) * rate

    def rate(self, currency: str, day: date) -> Decimal | None:
        if currency == PLN:
            return Decimal(1)
        rate = _last_on(self.rates.get(currency, ()), self.rate_days.get(currency, []), day)
        return None if rate is None else rate.rate

    def _rescaling(self, instrument_id: int, units_of: date, day: date) -> Decimal:
        """What turns a price in the units of ``units_of`` into one in the units of ``day``."""
        factor = Decimal(1)
        for split_day, ratio in self.splits.get(instrument_id, ()):
            if day < split_day <= units_of:
                factor *= Decimal(ratio.new) / ratio.old
            elif units_of < split_day <= day:
                factor *= Decimal(ratio.old) / ratio.new
        return factor

    def is_bond(self, instrument_id: int) -> bool:
        return self.instruments[instrument_id].asset_class_name in STAGE_3_CLASSES


def _last_on[T](values: Sequence[T], days: list[date], day: date) -> T | None:
    index = bisect_right(days, day)
    return values[index - 1] if index else None


def _splits(transactions: Iterable[TransactionDraft]) -> dict[int, list[tuple[date, SplitRatio]]]:
    """The Splits of each Instrument; one recorded on several Accounts counts once."""
    splits: dict[int, list[tuple[date, SplitRatio]]] = {}
    for t in transactions:
        if t.transaction_type is TransactionType.SPLIT:
            assert t.instrument_id is not None and t.split_ratio is not None
            recorded = splits.setdefault(t.instrument_id, [])
            if (t.date, t.split_ratio) not in recorded:
                recorded.append((t.date, t.split_ratio))
    return splits


# A Transaction's flows: (Account id or None for the whole Portfolio, PLN amount)
type _Flow = tuple[int | None, Decimal]


def _flows(transactions: Sequence[TransactionDraft], pricing: _Pricing) -> dict[int, list[_Flow]]:
    """The Net Deposits each Transaction adds, keyed by its ``id()``."""
    flows: dict[int, list[_Flow]] = {}
    for t in transactions:
        kind = t.transaction_type
        if kind in (TransactionType.DEPOSIT, TransactionType.WITHDRAWAL):
            amount = t.actual_amount if kind is TransactionType.DEPOSIT else -t.actual_amount
            flows[id(t)] = [(None, amount), (t.account_id, amount)]
        elif kind.is_transfer:
            assert t.target_account_id is not None
            amount = (
                t.actual_amount if kind is TransactionType.CASH_TRANSFER else _moved_value(transactions, t, pricing)
            )
            flows[id(t)] = [(t.account_id, -amount), (t.target_account_id, amount)]
    return flows


def _moved_value(transactions: Sequence[TransactionDraft], transfer: TransactionDraft, pricing: _Pricing) -> Decimal:
    """The units a Security Transfer moves at their value that day, or at the cost of their Lots without a price."""
    assert transfer.instrument_id is not None and transfer.quantity is not None
    unit = pricing.unit_pln(transfer.instrument_id, transfer.date)
    if unit is not None:
        return transfer.quantity * unit
    until = [t for t in transactions if t.date <= transfer.date]
    without = [t for t in until if t is not transfer]
    key = (transfer.target_account_id, transfer.instrument_id)

    def target_cost(positions: list[Position]) -> Decimal:
        return sum(
            (p.cost for p in positions if (p.account_id, p.instrument_id) == key),
            Decimal(0),
        )

    return target_cost(open_positions(until)) - target_cost(open_positions(without))


def _add_flows(
    net_deposits: Decimal, accounts: dict[int, Decimal], flows: Iterable[_Flow]
) -> tuple[Decimal, dict[int, Decimal]]:
    accounts = dict(accounts)
    for account_id, amount in flows:
        if account_id is None:
            net_deposits += amount
        else:
            accounts[account_id] = accounts.get(account_id, Decimal(0)) + amount
    return net_deposits, accounts


def _value(
    state: _State, pricing: _Pricing, day: date, net_deposits: Decimal, account_net_deposits: dict[int, Decimal]
) -> DayValue:
    accounts: dict[int, Decimal] = {}
    classes: dict[str, Decimal] = {}
    account_classes: dict[int, dict[str, Decimal]] = {}
    unpriced: set[int] = set()

    def add(account_id: int, value: Decimal, parts: Iterable[tuple[str, Decimal]]) -> None:
        """Add ``value`` to the Account, split into ``parts`` by Asset Class."""
        accounts[account_id] = accounts.get(account_id, Decimal(0)) + value
        held = account_classes.setdefault(account_id, {})
        for asset_class, part in parts:
            classes[asset_class] = classes.get(asset_class, Decimal(0)) + part
            held[asset_class] = held.get(asset_class, Decimal(0)) + part

    for account_id, balance in state.cash.items():
        add(account_id, balance, [(CASH_CLASS, balance)])
    unpriced_currencies: set[str] = set()
    for cash in state.foreign_cash:
        rate = pricing.rate(cash.currency, day)
        if rate is None:
            unpriced_currencies.add(cash.currency)
        value = cash.cost if rate is None else cash.value(rate)
        add(cash.account_id, value, [(FOREIGN_CASH_CLASS, value)])
    for position in state.positions:
        unit = pricing.unit_pln(position.instrument_id, day)
        if unit is None:
            value = position.cost
            if not pricing.is_bond(position.instrument_id):
                unpriced.add(position.instrument_id)
        else:
            value = position.quantity * unit
        # A Multi-asset Split spreads the value across its classes, the same split on every day (spec 6.1)
        add(position.account_id, value, pricing.instruments[position.instrument_id].class_parts(value))
    return DayValue(
        day,
        accounts,
        classes,
        net_deposits,
        account_net_deposits,
        frozenset(unpriced),
        frozenset(unpriced_currencies),
        account_classes,
    )
