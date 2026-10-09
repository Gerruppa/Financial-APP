"""The single FIFO Lot engine (spec 3.5, ADR-0003): Buys open Lots, Sells consume them oldest-first; foreign cash
is held as Lots the same way.

Each Lot carries an Actual cost (what really left the Account) and a Tax cost (at the NBP Rate).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financial_app.domain.formatting import format_date, format_quantity
from financial_app.domain.transactions import TransactionDraft, TransactionError, TransactionType

# Same-day order (spec 3.5) of the Transactions moving Lots: Buys before Sells, so a Sell may use shares bought
# that day, and DRIPs after them
_SAME_DAY_ORDER = {TransactionType.BUY: 0, TransactionType.SELL: 1, TransactionType.DRIP: 2}


class InsufficientQuantityError(TransactionError):
    """A Sell needs more units than the Account held that day; saving it is blocked (spec 3.3)."""

    def __init__(self, day: date, held: Decimal, requested: Decimal) -> None:
        super().__init__(
            f"Sprzedaż bez pokrycia: {format_date(day)} na koncie było {format_quantity(held)} szt., "
            f"a sprzedaż wymaga {format_quantity(requested)} szt."
        )
        self.day = day
        self.held = held
        self.requested = requested


@dataclass(frozen=True)
class Lot:
    """The still-open part of one Buy or DRIP (or of foreign cash coming in); ``cost`` is its Actual cost and
    ``tax_cost`` its Tax cost, in PLN.

    Both include the commission.
    """

    date: date
    quantity: Decimal
    cost: Decimal
    tax_cost: Decimal


@dataclass(frozen=True)
class Position:
    """All open Lots of one Instrument on one Account, oldest first."""

    account_id: int
    instrument_id: int
    lots: tuple[Lot, ...]

    @property
    def quantity(self) -> Decimal:
        return sum((lot.quantity for lot in self.lots), Decimal(0))

    @property
    def cost(self) -> Decimal:
        return sum((lot.cost for lot in self.lots), Decimal(0))

    @property
    def tax_cost(self) -> Decimal:
        return sum((lot.tax_cost for lot in self.lots), Decimal(0))

    @property
    def average_price(self) -> Decimal:
        """Cost per unit, commissions included."""
        return self.cost / self.quantity

    def value(self, price: Decimal) -> Decimal:
        return self.quantity * price

    def result(self, price: Decimal) -> Decimal:
        """Unrealised profit (or loss, if negative) in PLN at ``price``."""
        return self.value(price) - self.cost

    def result_percent(self, price: Decimal) -> Decimal:
        return self.result(price) / self.cost * 100


def open_positions(transactions: Iterable[TransactionDraft]) -> list[Position]:
    """The open Positions after all Buys, Sells and DRIPs, keyed by Account and Instrument.

    ``transactions`` come in entry order, which settles same-day ties after the Buy-before-Sell rule.
    Raises InsufficientQuantityError for the first Sell (by date) that is not covered.
    """
    buys_and_sells = sorted(
        (t for t in transactions if t.transaction_type in _SAME_DAY_ORDER),
        key=lambda t: (t.date, _SAME_DAY_ORDER[t.transaction_type]),
    )
    positions: dict[tuple[int, int], list[Lot]] = {}
    for t in buys_and_sells:
        assert (
            t.instrument_id is not None and t.quantity is not None
        )  # guaranteed for a Buy, Sell or DRIP by TransactionDraft
        lots = positions.setdefault((t.account_id, t.instrument_id), [])
        if t.transaction_type.opens_lot:
            lots.append(Lot(t.date, t.quantity, t.actual_amount, t.tax_amount))
        else:
            _consume(lots, t.date, t.quantity)
    return [
        Position(account_id, instrument_id, tuple(lots))
        for (account_id, instrument_id), lots in positions.items()
        if lots
    ]


@dataclass(frozen=True)
class ForeignCash:
    """The Cash Balance of one Account in one foreign currency, held as Lots with PLN costs (spec 3.5).

    Lots are positive, or negative while more was spent than held: insufficient cash only warns (spec 3.3), and
    the next incoming cash closes such a Lot. ``realized_result`` is the FX result of the cash already spent, in PLN.
    """

    account_id: int
    currency: str
    lots: tuple[Lot, ...]
    realized_result: Decimal

    @property
    def quantity(self) -> Decimal:
        return sum((lot.quantity for lot in self.lots), Decimal(0))

    @property
    def cost(self) -> Decimal:
        return sum((lot.cost for lot in self.lots), Decimal(0))

    def value(self, rate: Decimal) -> Decimal:
        """The PLN value at ``rate`` PLN per unit."""
        return self.quantity * rate

    def result(self, rate: Decimal) -> Decimal:
        """The unrealised FX result in PLN at ``rate``."""
        return self.value(rate) - self.cost


def foreign_cash(transactions: Iterable[TransactionDraft]) -> list[ForeignCash]:
    """Foreign cash per Account and currency after all Transactions, FIFO by date.

    Cash coming in (an Exchange from PLN, a Sell paid into foreign cash) opens a Lot at its PLN value; cash going
    out (an Exchange to PLN, a Buy paid from foreign cash) closes the oldest Lots, and the difference between its PLN
    value and their cost is the realised FX result. A PLN commission never touches foreign cash (spec 3.5).
    ``transactions`` come in entry order, which settles same-day ties after incoming-before-outgoing.
    """
    flows = sorted(
        (flow for t in transactions if (flow := _foreign_flow(t)) is not None),
        key=lambda flow: (flow.date, flow.quantity < 0),
    )
    lots: dict[tuple[int, str], list[Lot]] = {}
    realized: dict[tuple[int, str], Decimal] = {}
    for flow in flows:
        key = (flow.account_id, flow.currency)
        result = _net(lots.setdefault(key, []), Lot(flow.date, flow.quantity, flow.cost, flow.tax_cost))
        realized[key] = realized.get(key, Decimal(0)) + result
    return [
        ForeignCash(account_id, currency, tuple(open_lots), realized[(account_id, currency)])
        for (account_id, currency), open_lots in lots.items()
    ]


def fx_result(cash: Iterable[ForeignCash], account_id: int, rates: Mapping[str, Decimal]) -> Decimal:
    """The Account's FX result in PLN: realised plus unrealised at ``rates`` (PLN per unit) for each currency.

    A currency missing from ``rates`` adds only its realised result.
    """
    total = Decimal(0)
    for balance in cash:
        if balance.account_id == account_id:
            rate = rates.get(balance.currency)
            total += balance.realized_result + (Decimal(0) if rate is None else balance.result(rate))
    return total


@dataclass(frozen=True)
class _Flow:
    """Foreign cash moving in (positive) or out (negative), with its PLN value signed the same way."""

    account_id: int
    currency: str
    date: date
    quantity: Decimal
    cost: Decimal
    tax_cost: Decimal


def _foreign_flow(t: TransactionDraft) -> _Flow | None:
    change = t.foreign_cash_change
    if not change:
        return None
    if t.transaction_type is TransactionType.CURRENCY_EXCHANGE:
        value = tax_value = t.actual_amount
    else:
        # The Actual and Tax Amounts without the PLN commission, which is paid from PLN
        commission = t.commission if t.transaction_type is TransactionType.BUY else -t.commission
        value = t.actual_amount - commission
        tax_value = t.tax_amount - commission
    sign = 1 if change > 0 else -1
    return _Flow(t.account_id, t.cash_currency, t.date, change, sign * value, sign * tax_value)


def _net(lots: list[Lot], incoming: Lot) -> Decimal:
    """Close the oldest opposite-signed Lots with ``incoming``, keep any rest as a new Lot; return the realised result.

    Closing ``n`` units of a Lot with ``n`` units of the flow realises −(their two signed costs): what the cash
    brought (or cost) against what it had cost (or brought).
    """
    realized = Decimal(0)
    rest = incoming
    while rest.quantity and lots and (lots[0].quantity > 0) != (rest.quantity > 0):
        oldest = lots[0]
        units = min(abs(rest.quantity), abs(oldest.quantity))
        closed, oldest_left = _split(oldest, units)
        used, rest_left = _split(rest, units)
        realized -= closed.cost + used.cost
        if oldest_left.quantity:
            lots[0] = oldest_left
        else:
            lots.pop(0)
        rest = rest_left
    if rest.quantity:
        lots.append(rest)
    return realized


def _split(lot: Lot, units: Decimal) -> tuple[Lot, Lot]:
    """``units`` (unsigned) of ``lot`` and what is left of it, each with its costs pro rata."""
    share = units / abs(lot.quantity)
    taken = Lot(lot.date, lot.quantity * share, lot.cost * share, lot.tax_cost * share)
    left = Lot(lot.date, lot.quantity - taken.quantity, lot.cost - taken.cost, lot.tax_cost - taken.tax_cost)
    return taken, left


def _consume(lots: list[Lot], day: date, quantity: Decimal) -> None:
    """Take ``quantity`` units from the oldest Lots; a partly used Lot keeps both its costs pro rata."""
    held = sum((lot.quantity for lot in lots), Decimal(0))
    if quantity > held:
        raise InsufficientQuantityError(day, held, quantity)
    while quantity:
        oldest = lots[0]
        if quantity >= oldest.quantity:
            quantity -= oldest.quantity
            lots.pop(0)
        else:
            left = oldest.quantity - quantity
            share = left / oldest.quantity
            lots[0] = Lot(oldest.date, left, oldest.cost * share, oldest.tax_cost * share)
            quantity = Decimal(0)
