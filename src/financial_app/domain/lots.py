"""The single FIFO Lot engine (spec 3.5, ADR-0003): Buys open Lots, Sells consume them oldest-first.

Each Lot carries an Actual cost (what really left the Account) and a Tax cost (at the NBP Rate).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financial_app.domain.formatting import format_date, format_quantity
from financial_app.domain.transactions import TransactionDraft, TransactionError, TransactionType

# Same-day order (spec 3.5): Buys before Sells, so a Sell may use shares bought that day
_SAME_DAY_ORDER = {TransactionType.BUY: 0, TransactionType.SELL: 1}


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
    """The still-open part of one Buy; ``cost`` is its Actual cost and ``tax_cost`` its Tax cost, in PLN.

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
    """The open Positions after all Buys and Sells, keyed by Account and Instrument.

    ``transactions`` come in entry order, which settles same-day ties after the Buy-before-Sell rule.
    Raises InsufficientQuantityError for the first Sell (by date) that is not covered.
    """
    buys_and_sells = sorted(
        (t for t in transactions if t.transaction_type.is_buy_or_sell),
        key=lambda t: (t.date, _SAME_DAY_ORDER[t.transaction_type]),
    )
    positions: dict[tuple[int, int], list[Lot]] = {}
    for t in buys_and_sells:
        assert (
            t.instrument_id is not None and t.quantity is not None
        )  # guaranteed for a Buy or Sell by TransactionDraft
        lots = positions.setdefault((t.account_id, t.instrument_id), [])
        if t.transaction_type is TransactionType.BUY:
            lots.append(Lot(t.date, t.quantity, t.actual_amount, t.tax_amount))
        else:
            _consume(lots, t.date, t.quantity)
    return [
        Position(account_id, instrument_id, tuple(lots))
        for (account_id, instrument_id), lots in positions.items()
        if lots
    ]


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
