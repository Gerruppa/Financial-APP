"""The single FIFO Lot engine (spec 3.5, ADR-0003): Buys open Lots, Sells consume them oldest-first; foreign cash
is held as Lots the same way.

Each Lot carries an Actual cost (what really left the Account) and a Tax cost (at the NBP Rate).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from financial_app.domain.formatting import format_date, format_quantity
from financial_app.domain.transactions import TransactionDraft, TransactionError, TransactionType

# Same-day order (spec 3.5) of the Transactions moving Lots: a Split first, then Buys before Sells, so a Sell may
# use shares bought that day, and DRIPs after them. A Security Transfer comes between Buys and Sells, so units bought
# that day may move and the target Account may sell them the same day.
_SAME_DAY_ORDER = {
    TransactionType.SPLIT: 0,
    TransactionType.BUY: 1,
    TransactionType.SECURITY_TRANSFER: 2,
    TransactionType.SELL: 3,
    TransactionType.DRIP: 4,
}


class InsufficientQuantityError(TransactionError):
    """A Sell or Security Transfer needs more units than the Account held that day; saving it is blocked (spec 3.3)."""

    def __init__(
        self, day: date, held: Decimal, requested: Decimal, kind: TransactionType = TransactionType.SELL
    ) -> None:
        what = "transfer" if kind is TransactionType.SECURITY_TRANSFER else "sprzedaż"
        super().__init__(
            f"{what.capitalize()} bez pokrycia: {format_date(day)} na koncie było {format_quantity(held)} szt., "
            f"a {what} wymaga {format_quantity(requested)} szt."
        )
        self.day = day
        self.held = held
        self.requested = requested


class SplitBeforeFirstBuyError(TransactionError):
    """A Split dated before the Account first held the Instrument; saving it is blocked (spec 3.3)."""

    def __init__(self, day: date) -> None:
        super().__init__(f"Split przed pierwszym zakupem: {format_date(day)} konto nie miało jeszcze tego instrumentu.")
        self.day = day


@dataclass(frozen=True)
class FxBasis:
    """What a foreign-currency Lot cost: ``foreign`` in the Instrument's currency (quantity × price, a DRIP's net
    amount) and ``pln``, that amount in PLN at the rate paid, without the commission and the FX Conversion Fee."""

    foreign: Decimal
    pln: Decimal

    def fx_result(self, rate: Decimal) -> Decimal:
        """How much more (or less) in PLN the foreign amount is worth at ``rate`` than it cost."""
        return self.foreign * rate - self.pln


@dataclass(frozen=True)
class Lot:
    """The still-open part of one Buy or DRIP (or of foreign cash coming in); ``cost`` is its Actual cost and
    ``tax_cost`` its Tax cost, in PLN.

    Both include the commission. A Lot of a foreign-currency Instrument also has its ``fx_basis``, so its result
    splits into a price and an FX effect (issue #89).
    """

    date: date
    quantity: Decimal
    cost: Decimal
    tax_cost: Decimal
    fx_basis: FxBasis | None = None

    def part(self, share: Decimal) -> Lot:
        """``share`` (a fraction) of the Lot: its units, costs and FX basis pro rata."""
        basis = self.fx_basis
        return Lot(
            self.date,
            self.quantity * share,
            self.cost * share,
            self.tax_cost * share,
            None if basis is None else FxBasis(basis.foreign * share, basis.pln * share),
        )

    def rest(self, taken: Lot) -> Lot:
        """What is left of the Lot once ``taken``, a part of it, is gone."""
        basis, used = self.fx_basis, taken.fx_basis
        return Lot(
            self.date,
            self.quantity - taken.quantity,
            self.cost - taken.cost,
            self.tax_cost - taken.tax_cost,
            None if basis is None or used is None else FxBasis(basis.foreign - used.foreign, basis.pln - used.pln),
        )


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

    def value_or_cost(self, price: Decimal | None) -> Decimal:
        """The value at ``price``, or the cost without one."""
        return self.cost if price is None else self.value(price)

    def result(self, price: Decimal) -> Decimal:
        """Unrealised profit (or loss, if negative) in PLN at ``price``."""
        return self.value(price) - self.cost

    def result_percent(self, price: Decimal) -> Decimal:
        return self.result(price) / self.cost * 100

    def fx_result(self, rate: Decimal) -> Decimal:
        """The FX part of the unrealised result at ``rate`` PLN per unit of the Instrument's currency: how much more
        (or less) the Lots' cost in that currency is worth than it cost in PLN; 0 for a PLN Instrument."""
        return sum((lot.fx_basis.fx_result(rate) for lot in self.lots if lot.fx_basis), Decimal(0))


def open_positions(transactions: Iterable[TransactionDraft]) -> list[Position]:
    """The open Positions after all Buys, Sells, DRIPs, Splits and Security Transfers, keyed by Account and Instrument.

    A Split rescales the open Lots' units, keeping their costs; a Security Transfer moves the oldest Lots to the
    target Account with their dates and costs, where they take their place by date. ``transactions`` come in entry
    order, which settles same-day ties after the same-day order. Raises InsufficientQuantityError for the first Sell
    or Security Transfer (by date) that is not covered, and SplitBeforeFirstBuyError for a Split before the Account
    first held the Instrument.
    """
    positions, _, _ = _replay(transactions)
    return [
        Position(account_id, instrument_id, tuple(lots))
        for (account_id, instrument_id), lots in positions.items()
        if lots
    ]


def realized_results(transactions: Iterable[TransactionDraft]) -> dict[int, Decimal]:
    """The realised result of Sells in PLN per Account: each Sell's Actual Amount (net of its commission) less the
    Actual cost of the Lots it consumed, FIFO as in ``open_positions``. Only Accounts with a Sell are keys."""
    _, realized, _ = _replay(transactions)
    return realized


def realized_fx_results(transactions: Iterable[TransactionDraft]) -> dict[int, Decimal]:
    """The FX part of ``realized_results`` per Account: how much more (or less) in PLN the sold Lots' cost in the
    Instrument's currency brought at the Sell's rate than it cost at theirs. Only Accounts with a foreign-currency Sell
    are keys."""
    _, _, realized_fx = _replay(transactions)
    return realized_fx


def _replay(
    transactions: Iterable[TransactionDraft],
) -> tuple[dict[tuple[int, int], list[Lot]], dict[int, Decimal], dict[int, Decimal]]:
    """The open Lots per Account and Instrument, the realised result and its FX part per Account (see
    ``open_positions``)."""
    moves = sorted(
        (t for t in transactions if t.transaction_type in _SAME_DAY_ORDER),
        key=lambda t: (t.date, _SAME_DAY_ORDER[t.transaction_type]),
    )
    positions: dict[tuple[int, int], list[Lot]] = {}
    realized: dict[int, Decimal] = {}
    realized_fx: dict[int, Decimal] = {}
    ever_held: set[tuple[int, int]] = set()
    for t in moves:
        assert t.instrument_id is not None  # guaranteed for these types by TransactionDraft
        key = (t.account_id, t.instrument_id)
        lots = positions.setdefault(key, [])
        if t.transaction_type is TransactionType.SPLIT:
            assert t.split_ratio is not None
            if key not in ever_held:
                raise SplitBeforeFirstBuyError(t.date)
            ratio = t.split_ratio
            lots[:] = [replace(lot, quantity=ratio.rescale(lot.quantity)) for lot in lots]
            continue
        assert t.quantity is not None
        if t.transaction_type.opens_lot:
            lots.append(Lot(t.date, t.quantity, t.actual_amount, t.tax_amount, _fx_basis(t)))
            ever_held.add(key)
        elif t.transaction_type is TransactionType.SECURITY_TRANSFER:
            assert t.target_account_id is not None
            moved = _consume(lots, t.date, t.quantity, t.transaction_type)
            target_key = (t.target_account_id, t.instrument_id)
            # Stable, so a moved Lot dated like one already there comes after it
            positions[target_key] = sorted([*positions.get(target_key, []), *moved], key=lambda lot: lot.date)
            ever_held.add(target_key)
        else:
            sold = _consume(lots, t.date, t.quantity, t.transaction_type)
            cost = sum((lot.cost for lot in sold), Decimal(0))
            realized[t.account_id] = realized.get(t.account_id, Decimal(0)) + t.actual_amount - cost
            sold_basis = _fx_basis(t)
            if sold_basis is not None:
                rate = sold_basis.pln / sold_basis.foreign
                fx = sum((lot.fx_basis.fx_result(rate) for lot in sold if lot.fx_basis), Decimal(0))
                realized_fx[t.account_id] = realized_fx.get(t.account_id, Decimal(0)) + fx
    return positions, realized, realized_fx


def _fx_basis(t: TransactionDraft) -> FxBasis | None:
    """The foreign amount of a foreign-currency Buy, Sell or DRIP and its PLN at the rate paid (the market rate,
    without the broker's FX Conversion Fee); ``None`` for a PLN one."""
    if t.nbp_rate is None:
        return None
    if t.transaction_type is TransactionType.DRIP:
        return FxBasis(t.net, t.actual_amount) if t.net else None
    assert t.quantity is not None and t.price is not None  # a Buy or Sell, checked on creation
    foreign = t.quantity * t.price
    return FxBasis(foreign, t.market_amount) if foreign else None


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
    taken = lot.part(share)
    return taken, lot.rest(taken)


def _consume(lots: list[Lot], day: date, quantity: Decimal, kind: TransactionType) -> list[Lot]:
    """Take ``quantity`` units from the oldest Lots and return them; a partly used Lot splits both costs pro rata.

    ``kind`` (a Sell or Security Transfer) names the Transaction in the error.
    """
    held = sum((lot.quantity for lot in lots), Decimal(0))
    if quantity > held:
        raise InsufficientQuantityError(day, held, quantity, kind)
    taken = []
    while quantity:
        oldest = lots[0]
        if quantity >= oldest.quantity:
            quantity -= oldest.quantity
            taken.append(lots.pop(0))
        else:
            rest = oldest.part((oldest.quantity - quantity) / oldest.quantity)
            lots[0] = rest
            taken.append(oldest.rest(rest))
            quantity = Decimal(0)
    return taken
