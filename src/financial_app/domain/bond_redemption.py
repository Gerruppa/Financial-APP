"""What redeeming a retail treasury bond would pay (spec 3.4.1, L-4): its gross value less the early-redemption fee and
the tax withheld on its profit, computed for one bond as the issue letters do.

The MF file does not carry the early-redemption fee, so the app has its own table, updated with app releases: each bond
type's fee per bond from the first issue it applies to. The fee is capped at the accrued interest and none is due at
maturity. An OTS has no fee but forfeits its interest when redeemed early, so that interest counts as its fee. The tax
is the Account's Tax Regime's (Belka, none in IKE or IKZE) on the profit of one bond over its Tax cost, rounded half up
to the grosz; a bond bought in a Rollover below its nominal is taxed on that discount too.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from financial_app.domain.bond_valuation import GROSZ, BondPrice
from financial_app.domain.bonds import ISSUE_PRICE, BondSeries, BondType, maturity, sale_month
from financial_app.domain.lots import Lot

# The fee per bond from the first month of sale it applies to, oldest first; an older issue pays the first fee listed.
# MF raised them from the September 2024 issues (OTS is redeemed early without a fee, but also without interest).
EARLY_REDEMPTION_FEES: dict[BondType, tuple[tuple[date, Decimal], ...]] = {
    BondType.OTS: ((date(1999, 1, 1), Decimal(0)),),
    BondType.ROR: ((date(1999, 1, 1), Decimal("0.50")),),
    BondType.DOR: ((date(1999, 1, 1), Decimal("0.70")),),
    BondType.TOS: ((date(1999, 1, 1), Decimal("0.70")), (date(2024, 9, 1), Decimal("1.00"))),
    BondType.COI: ((date(1999, 1, 1), Decimal("0.70")), (date(2024, 9, 1), Decimal("2.00"))),
    BondType.EDO: ((date(1999, 1, 1), Decimal("2.00")), (date(2024, 9, 1), Decimal("3.00"))),
    BondType.ROS: ((date(1999, 1, 1), Decimal("0.70")), (date(2024, 9, 1), Decimal("2.00"))),
    BondType.ROD: ((date(1999, 1, 1), Decimal("2.00")), (date(2024, 9, 1), Decimal("3.00"))),
}
# The types that pay no interest when redeemed early, only the nominal
FORFEITING_TYPES = frozenset({BondType.OTS})


def early_redemption_fee(series: BondSeries) -> Decimal:
    """The fee per bond of ``series`` redeemed before maturity, before the cap at the accrued interest."""
    sold = sale_month(series.name)
    fees = EARLY_REDEMPTION_FEES[series.bond_type]
    return next((fee for start, fee in reversed(fees) if start <= sold), fees[0][1])


@dataclass(frozen=True)
class NetValue:
    """One bond on a day: its ``gross`` value, the early-redemption ``fee`` and the ``tax`` withheld, in PLN."""

    gross: Decimal
    fee: Decimal
    tax: Decimal

    @property
    def deductions(self) -> Decimal:
        """The fee and the tax together, which the after-tax toggle takes off the gross value."""
        return self.fee + self.tax

    @property
    def net(self) -> Decimal:
        """What redeeming the bond that day would pay."""
        return self.gross - self.deductions


def net_value(price: BondPrice, lot: Lot, tax_rate: Decimal) -> NetValue | None:
    """One bond of ``lot`` redeemed on ``price``'s day, with ``tax_rate`` (a fraction) withheld from its profit;
    ``None`` while the Series has no value."""
    value = price.value(lot.date)
    if value is None:
        return None
    gross = value.value
    interest = max(gross - ISSUE_PRICE, Decimal(0))
    if price.day >= maturity(price.series.bond_type, lot.date):
        fee = Decimal(0)
    elif price.series.bond_type in FORFEITING_TYPES:
        fee = interest
    else:
        fee = min(early_redemption_fee(price.series), interest)
    profit = gross - fee - lot.tax_cost / lot.quantity
    tax = (tax_rate * max(profit, Decimal(0))).quantize(GROSZ, ROUND_HALF_UP)
    return NetValue(gross, fee, tax)


@dataclass(frozen=True)
class EarlyRedemption:
    """What the "+" dialog prefills a Sell of a Bond Series with (spec 3.4.1), and a maturity Draft saves (no fee
    then): the gross value of one bond as the
    ``price``, the early-redemption ``fee`` as the commission and the ``tax`` withheld, both for all the bonds redeemed,
    in PLN."""

    price: Decimal
    fee: Decimal
    tax: Decimal
    quantity: Decimal

    @property
    def gross(self) -> Decimal:
        """The gross value of all the bonds redeemed."""
        return self.quantity * self.price

    @property
    def net(self) -> Decimal:
        """What the redemption pays out: its Actual Amount."""
        return self.gross - self.fee - self.tax


def early_redemption(price: BondPrice, lot: Lot, quantity: Decimal, tax_rate: Decimal) -> EarlyRedemption | None:
    """Redeeming ``quantity`` bonds of ``lot`` on ``price``'s day, each as ``net_value`` gives it; ``None`` while the
    Series has no value."""
    per_bond = net_value(price, lot, tax_rate)
    if per_bond is None:
        return None
    return EarlyRedemption(per_bond.gross, quantity * per_bond.fee, quantity * per_bond.tax, quantity)
