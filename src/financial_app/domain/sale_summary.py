"""The Sell Summary (issue #92, spec 10): each Sale Pair, the part of a Lot one Sell closed, from the single FIFO
engine (ADR-0003), so DRIPs, Splits, Security Transfers and Early Redemptions count as in the Portfolio (fixing the
sheet's bug 7, spec 9), and the statistics of the closed positions.

A pair's cost is the Lot's Actual cost (its commission included), its revenue the Sell's Actual Amount pro rata to the
units (net of the commission, of an Early Redemption's fee and its withheld tax). The Dividends attributed to a pair
are its share of each net Dividend and DRIP of the Instrument on the Account: a Dividend paid on a day goes to the
units held at the end of the day before, per unit (so one paid on the sale day is still the pair's, one on the buy day
is not); one paid after the whole position was sold, within ``DIVIDEND_AFTER_SALE`` of the last sale and before buying
again, goes to that sale's pairs. A coupon (interest naming its Lot) goes to that Lot's units the same way. A Lot moved
by a Security Transfer counts as held on the Account it was sold from (a documented simplification).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from financial_app.domain.lots import ClosedLot, open_positions, replay
from financial_app.domain.transactions import Transaction, TransactionDraft, TransactionType

# How long after selling everything a Dividend may still be paid for the sold units (record day before the sale)
DIVIDEND_AFTER_SALE = timedelta(days=90)


@dataclass(frozen=True)
class SalePair:
    """The units of one Lot one Sell closed: bought on ``bought_on``, sold on ``sold_on``; ``quantity`` in the units
    of the sale day; ``cost``, ``revenue`` and the attributed net ``dividends`` in PLN."""

    account_id: int
    instrument_id: int
    bought_on: date
    sold_on: date
    quantity: Decimal
    cost: Decimal
    revenue: Decimal
    dividends: Decimal = Decimal(0)

    @property
    def result(self) -> Decimal:
        return self.revenue - self.cost

    @property
    def return_rate(self) -> Decimal | None:
        """The result as a fraction of the cost; ``None`` for a pair that cost nothing."""
        return self.result / self.cost if self.cost else None

    @property
    def result_with_dividends(self) -> Decimal:
        return self.result + self.dividends

    @property
    def return_with_dividends(self) -> Decimal | None:
        return self.result_with_dividends / self.cost if self.cost else None

    @property
    def days_held(self) -> int:
        return (self.sold_on - self.bought_on).days


@dataclass(frozen=True)
class SaleStats:
    """The statistics of some Sale Pairs: how many, the share with a profit (``win_rate``, a fraction), the average
    days held, the ``best`` and ``worst`` by result, and the sums in PLN."""

    count: int
    win_rate: Decimal
    average_days: Decimal
    best: SalePair
    worst: SalePair
    cost: Decimal
    revenue: Decimal
    result: Decimal
    dividends: Decimal

    @property
    def result_with_dividends(self) -> Decimal:
        return self.result + self.dividends

    @property
    def return_rate(self) -> Decimal | None:
        return self.result / self.cost if self.cost else None

    @property
    def return_with_dividends(self) -> Decimal | None:
        return self.result_with_dividends / self.cost if self.cost else None


def sale_pairs(transactions: Sequence[TransactionDraft]) -> list[SalePair]:
    """Every Sale Pair of ``transactions`` (in entry order, for the FIFO engine's same-day ties), by the Sells' date,
    each Sell's oldest Lot first, with its Dividends."""
    closed = replay(transactions).closed
    shares = [Decimal(0)] * len(closed)
    for paid in transactions:
        if paid.transaction_type.is_dividend:
            for index, share in _attribute(paid, closed, transactions):
                shares[index] += share
    return [
        SalePair(
            piece.account_id,
            piece.instrument_id,
            piece.lot.date,
            piece.sell.date,
            piece.lot.quantity,
            piece.lot.cost,
            piece.revenue,
            share,
        )
        for piece, share in zip(closed, shares, strict=True)
    ]


def in_view(pairs: Iterable[SalePair], account_id: int | None, first: date, last: date) -> list[SalePair]:
    """The pairs of the View Scope (``account_id``, ``None`` for Total) sold from ``first`` to ``last``, newest sale
    first (each sale's oldest Lot first)."""
    kept = [p for p in pairs if account_id in (None, p.account_id) and first <= p.sold_on <= last]
    return sorted(kept, key=lambda p: p.sold_on, reverse=True)


def sale_stats(pairs: Sequence[SalePair]) -> SaleStats | None:
    """The statistics of ``pairs``; ``None`` without any."""
    if not pairs:
        return None
    count = len(pairs)
    return SaleStats(
        count,
        Decimal(sum(1 for p in pairs if p.result > 0)) / count,
        Decimal(sum(p.days_held for p in pairs)) / count,
        max(pairs, key=lambda p: p.result),
        min(pairs, key=lambda p: p.result),
        sum((p.cost for p in pairs), Decimal(0)),
        sum((p.revenue for p in pairs), Decimal(0)),
        sum((p.result for p in pairs), Decimal(0)),
        sum((p.dividends for p in pairs), Decimal(0)),
    )


def _attribute(
    paid: TransactionDraft, closed: Sequence[ClosedLot], transactions: Sequence[TransactionDraft]
) -> list[tuple[int, Decimal]]:
    """The shares of the Dividend ``paid`` going to the pieces of ``closed`` (by index); the rest stays with the
    units still held."""
    instrument_id, lot_id = paid.instrument_id, None
    if instrument_id is None:
        # Interest: a coupon names the Lot it was paid on, anything else belongs to no Instrument
        lot_id = paid.lot_id
        opened = next((t for t in transactions if isinstance(t, Transaction) and t.id == lot_id), None)
        if opened is None or opened.instrument_id is None:
            return []
        instrument_id = opened.instrument_id
    account_id, day = paid.account_id, paid.date
    traded = [t for t in transactions if t.instrument_id == instrument_id]

    def ours(piece: ClosedLot) -> bool:
        same = (piece.account_id, piece.instrument_id) == (account_id, instrument_id)
        return same and (lot_id is None or piece.lot.opened_by == lot_id)

    held = sum(
        (
            lot.quantity
            for position in open_positions([t for t in traded if t.date < day])
            if position.account_id == account_id
            for lot in position.lots
            if lot_id is None or lot.opened_by == lot_id
        ),
        Decimal(0),
    )
    if held:
        units = {
            index: _units_before(piece, day, traded)
            for index, piece in enumerate(closed)
            if ours(piece) and piece.lot.date < day <= piece.sell.date
        }
        return [(index, paid.actual_amount * quantity / held) for index, quantity in units.items()]
    return _after_sale(paid, [(index, piece) for index, piece in enumerate(closed) if ours(piece)], traded)


def _after_sale(
    paid: TransactionDraft, pieces: Sequence[tuple[int, ClosedLot]], traded: Sequence[TransactionDraft]
) -> list[tuple[int, Decimal]]:
    """The shares of a Dividend paid with nothing held: all of it to the last sale's pieces, when it came within
    ``DIVIDEND_AFTER_SALE`` of it and nothing was bought again in between."""
    before = [(index, piece) for index, piece in pieces if piece.sell.date < paid.date]
    if not before:
        return []
    sold_on = max(piece.sell.date for _, piece in before)
    bought_again = any(
        t.account_id == paid.account_id and t.transaction_type.opens_lot and sold_on < t.date < paid.date
        for t in traded
    )
    if paid.date - sold_on > DIVIDEND_AFTER_SALE or bought_again:
        return []
    last = [(index, piece) for index, piece in before if piece.sell.date == sold_on]
    units = sum((piece.lot.quantity for _, piece in last), Decimal(0))
    return [(index, paid.actual_amount * piece.lot.quantity / units) for index, piece in last]


def _units_before(piece: ClosedLot, day: date, traded: Sequence[TransactionDraft]) -> Decimal:
    """The piece's units at the end of the day before ``day``: those of its sale day undone by the Splits recorded on
    its Account from ``day`` up to the sale."""
    quantity = piece.lot.quantity
    for t in traded:
        if (
            t.transaction_type is TransactionType.SPLIT
            and t.account_id == piece.account_id
            and day <= t.date <= piece.sell.date
        ):
            assert t.split_ratio is not None  # a Split has one
            quantity = quantity * t.split_ratio.old / t.split_ratio.new
    return quantity
