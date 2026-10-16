"""The Obligacje tab's table (spec 3.4.1, L-4): each Bond Series held on an Account, expanding to its Lots.

A Series shows how many bonds it holds, what was paid in, the current period and its rate (the oldest Lot's, with the
most uncertain label of any Lot), the gross value by the MF issue letters, the net value (after the early-redemption fee
and the tax the Account's Tax Regime withholds), the next anniversary and the maturity. A Series not valued yet stays at
cost without a net value. The tab values Series by the MF issue letters even when a Manual Price overrides them
elsewhere.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account, tax_regime_for
from financial_app.domain.bond_redemption import NetValue, net_value
from financial_app.domain.bond_valuation import BondData, BondValue, RateLabel, most_uncertain, next_anniversary
from financial_app.domain.bonds import bond_type_of, maturity
from financial_app.domain.instruments import Instrument
from financial_app.domain.lots import Lot, Position


@dataclass(frozen=True)
class LotHolding:
    """One Lot of a Series: one bond's ``value`` and ``per_bond`` Net Value (``None`` while the Series has no value)."""

    lot: Lot
    value: BondValue | None
    per_bond: NetValue | None
    next_anniversary: date | None
    maturity: date

    @property
    def gross(self) -> Decimal:
        """The Lot's gross value, its cost without a value."""
        return self.lot.cost if self.value is None else self.lot.quantity * self.value.value

    @property
    def net(self) -> Decimal | None:
        """The Lot's Net Value."""
        return None if self.per_bond is None else self.lot.quantity * self.per_bond.net

    @property
    def fee(self) -> Decimal:
        return Decimal(0) if self.per_bond is None else self.lot.quantity * self.per_bond.fee

    @property
    def tax(self) -> Decimal:
        return Decimal(0) if self.per_bond is None else self.lot.quantity * self.per_bond.tax


@dataclass(frozen=True)
class SeriesHolding:
    """A Bond Series held on ``account``, with its Lots oldest first."""

    account: Account
    instrument: Instrument
    lots: tuple[LotHolding, ...]

    @property
    def quantity(self) -> Decimal:
        return sum((held.lot.quantity for held in self.lots), Decimal(0))

    @property
    def paid(self) -> Decimal:
        return sum((held.lot.cost for held in self.lots), Decimal(0))

    @property
    def gross(self) -> Decimal:
        return sum((held.gross for held in self.lots), Decimal(0))

    @property
    def net(self) -> Decimal | None:
        """The net value of every Lot, ``None`` while any has none."""
        nets = [held.net for held in self.lots]
        return None if None in nets else sum((n for n in nets if n is not None), Decimal(0))

    @property
    def current(self) -> BondValue | None:
        """The oldest Lot's value, which gives the current period and its rate."""
        return self.lots[0].value

    @property
    def label(self) -> RateLabel | None:
        return most_uncertain(held.value.label for held in self.lots if held.value is not None)

    @property
    def next_anniversary(self) -> date | None:
        return min((d for held in self.lots if (d := held.next_anniversary) is not None), default=None)

    @property
    def maturity(self) -> date:
        return min(held.maturity for held in self.lots)


def bond_holdings(
    positions: Iterable[Position],
    instruments: Mapping[int, Instrument],
    accounts: Sequence[Account],
    bonds: BondData,
    day: date,
    account_id: int | None,
) -> list[SeriesHolding]:
    """The Bond Series among ``positions`` on ``day``, in the View Scope (``account_id``, ``None`` for Total), largest
    gross value first."""
    by_id = {account.id: account for account in accounts}
    holdings = []
    for position in positions:
        instrument = instruments[position.instrument_id]
        bond_type = bond_type_of(instrument.name)
        # A Bond Series always has a type; the check only narrows it
        if not instrument.is_bond_series or bond_type is None or account_id not in (None, position.account_id):
            continue
        account = by_id[position.account_id]
        tax_rate = tax_regime_for(account.account_type).withheld_tax_rate
        price = bonds.price(instrument.id, day)
        lots = tuple(
            LotHolding(
                lot,
                None if price is None else price.value(lot.date),
                None if price is None else net_value(price, lot, tax_rate),
                next_anniversary(bond_type, lot.date, day),
                maturity(bond_type, lot.date),
            )
            for lot in position.lots
        )
        holdings.append(SeriesHolding(account, instrument, lots))
    return sorted(holdings, key=lambda holding: holding.gross, reverse=True)


@dataclass(frozen=True)
class BondTotals:
    """The sums of the Series listed; the ``net`` sum counts a Series not valued yet at its gross value (its cost)."""

    paid: Decimal
    gross: Decimal
    net: Decimal


def bond_totals(holdings: Iterable[SeriesHolding]) -> BondTotals:
    held = list(holdings)
    return BondTotals(
        sum((h.paid for h in held), Decimal(0)),
        sum((h.gross for h in held), Decimal(0)),
        sum((h.gross if h.net is None else h.net for h in held), Decimal(0)),
    )
