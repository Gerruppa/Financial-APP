"""Maturity, Rollover and coupons as Drafts (spec 3.4.1, L-6, L-8): a Lot of a Bond Series still held on or after its
maturity has not been redeemed in the app yet, and a coupon of a COI, ROR or DOR Lot paid by today not entered yet, so
each shows in the Obligacje tab's "Do zatwierdzenia" list.

Drafts are computed from the Lots, never stored: confirming a maturity saves an ordinary Sell of that Lot on its
maturity day (at one bond's maturity value, no fee, the Account's Tax Regime's tax withheld), and a Rollover adds the
Buy of a new Series on the same day at its Rollover price. Once saved, the Lot is gone and so is the Draft. Confirming a
coupon saves an interest Dividend (no Instrument) naming the Lot, on the coupon's day, with the tax withheld on the
coupon of one bond. The interest Dividends naming a Lot tell how many of its coupons were entered, the oldest first,
so editing one's day to the bank's statement keeps it entered. A coupon is drafted for the bonds the Lot holds now, so
a Lot partly redeemed after a coupon was due drafts it for the bonds left; interest entered without naming the Lot (as
the sheet import saves it) does not count.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from financial_app.domain.accounts import Account, tax_regime_for
from financial_app.domain.bond_redemption import EarlyRedemption, early_redemption
from financial_app.domain.bond_valuation import GROSZ, BondData, Coupon
from financial_app.domain.bonds import FAMILY_TYPES, BondType, bond_type_of, maturity, series_name
from financial_app.domain.formatting import format_quantity
from financial_app.domain.instruments import Instrument
from financial_app.domain.lots import Lot, Position
from financial_app.domain.transactions import (
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
    dividend,
)

# The types a Rollover may buy: any but the family bonds, which only the 800+ benefit buys
ROLLOVER_TYPES = tuple(bond_type for bond_type in BondType if bond_type not in FAMILY_TYPES)


@dataclass(frozen=True)
class MaturityDraft:
    """A ``lot`` of a Bond Series on ``account`` that matured on ``maturity`` and is still held. ``redemption`` is what
    redeeming all its bonds that day pays (``None`` while the Series has no value, without its first rate, so it is
    entered by hand)."""

    account: Account
    instrument: Instrument
    bond_type: BondType
    lot: Lot
    maturity: date
    redemption: EarlyRedemption | None

    @property
    def due(self) -> date:
        return self.maturity

    def rollover_series(self, bond_type: BondType) -> str:
        """The Series of ``bond_type`` a Rollover buys: the one sold in the month the Lot matures."""
        return series_name(bond_type, self.maturity)

    def transaction(self) -> TransactionDraft:
        """The Sell redeeming the whole Lot on its maturity day."""
        assert self.redemption is not None, "a Series without a value is redeemed by hand"
        return buy_or_sell(
            self.account.id,
            self.maturity,
            TransactionType.SELL,
            self.instrument.id,
            self.redemption.quantity,
            self.redemption.price,
            self.redemption.fee,
            "Wykup w terminie",
            withholding_tax=self.redemption.tax,
            lot_id=self.lot.opened_by,
        )

    def rollover_purchase(self, instrument_id: int, quantity: Decimal, price: Decimal) -> TransactionDraft:
        """The Buy of ``quantity`` bonds of the new Series ``instrument_id`` at its Rollover ``price``, on the day the
        Lot matures; a Rollover exchanges only the bonds redeemed."""
        if quantity > self.lot.quantity:
            raise TransactionError(f"Zamiana obejmuje najwyżej {format_quantity(self.lot.quantity)} obligacji.")
        return buy_or_sell(
            self.account.id,
            self.maturity,
            TransactionType.BUY,
            instrument_id,
            quantity,
            price,
            comment=f"Zamiana z {self.instrument.name}",
        )


def maturity_drafts(
    positions: Iterable[Position],
    instruments: Mapping[int, Instrument],
    accounts: Sequence[Account],
    bonds: BondData,
    day: date,
    account_id: int | None,
) -> list[MaturityDraft]:
    """The Lots of Bond Series among ``positions`` matured by ``day``, in the View Scope (``account_id``, ``None`` for
    Total), the earliest maturity first."""
    by_id = {account.id: account for account in accounts}
    drafts = []
    for position in positions:
        instrument = instruments[position.instrument_id]
        bond_type = bond_type_of(instrument.name)
        # A Bond Series always has a type; the check only narrows it
        if not instrument.is_bond_series or bond_type is None or account_id not in (None, position.account_id):
            continue
        account = by_id[position.account_id]
        tax_rate = tax_regime_for(account.account_type).withheld_tax_rate
        for lot in position.lots:
            matured = maturity(bond_type, lot.date)
            if matured > day:
                continue
            price = bonds.price(instrument.id, matured)
            redemption = None if price is None else early_redemption(price, lot, lot.quantity, tax_rate)
            drafts.append(MaturityDraft(account, instrument, bond_type, lot, matured, redemption))
    return sorted(drafts, key=lambda draft: (draft.maturity, draft.account.name, draft.instrument.name))


@dataclass(frozen=True)
class CouponDraft:
    """A ``coupon`` of a ``lot`` of a coupon-paying Bond Series on ``account``, not entered yet; ``tax_rate`` is the
    Account's Tax Regime's, withheld on the coupon of one bond."""

    account: Account
    instrument: Instrument
    lot: Lot
    coupon: Coupon
    tax_rate: Decimal

    @property
    def due(self) -> date:
        return self.coupon.day

    @property
    def period(self) -> int:
        return self.coupon.period

    @property
    def gross(self) -> Decimal:
        return self.lot.quantity * self.coupon.amount

    @property
    def tax(self) -> Decimal:
        return self.lot.quantity * (self.tax_rate * self.coupon.amount).quantize(GROSZ, ROUND_HALF_UP)

    @property
    def net(self) -> Decimal:
        return self.gross - self.tax

    def transaction(self) -> TransactionDraft:
        """The interest Dividend paying the coupon into the Account's PLN cash, naming the Lot."""
        return dividend(
            self.account.id,
            self.coupon.day,
            self.gross,
            self.tax,
            f"Odsetki {self.instrument.name} · okres {self.period}",
            lot_id=self.lot.opened_by,
        )


def coupon_drafts(
    positions: Iterable[Position],
    instruments: Mapping[int, Instrument],
    accounts: Sequence[Account],
    bonds: BondData,
    day: date,
    account_id: int | None,
    entered: Mapping[int, int],
) -> list[CouponDraft]:
    """The coupons of the Lots among ``positions`` paid by ``day`` and not entered (``entered`` counts them by the
    Lot, as the id of the Transaction opening it), in the View Scope, the earliest first."""
    by_id = {account.id: account for account in accounts}
    drafts: list[CouponDraft] = []
    for position in positions:
        instrument = instruments[position.instrument_id]
        price = bonds.price(instrument.id, day) if instrument.is_bond_series else None
        if price is None or account_id not in (None, position.account_id):
            continue
        account = by_id[position.account_id]
        tax_rate = tax_regime_for(account.account_type).withheld_tax_rate
        for lot in position.lots:
            done = 0 if lot.opened_by is None else entered.get(lot.opened_by, 0)
            drafts.extend(
                CouponDraft(account, instrument, lot, coupon, tax_rate) for coupon in price.coupons(lot.date)[done:]
            )
    return sorted(drafts, key=lambda draft: (draft.due, draft.account.name, draft.instrument.name))


# A Draft of either kind: each has its ``due`` day and the ``transaction()`` confirming it saves
type BondDraft = MaturityDraft | CouponDraft


def coupons_entered(transactions: Iterable[TransactionDraft]) -> Counter[int]:
    """How many coupons of each Lot (by the id of the Transaction opening it) were entered: the interest Dividends
    naming it."""
    return Counter(
        t.lot_id for t in transactions if t.transaction_type is TransactionType.DIVIDEND and t.lot_id is not None
    )


def bond_drafts(
    positions: Sequence[Position],
    instruments: Mapping[int, Instrument],
    accounts: Sequence[Account],
    bonds: BondData,
    day: date,
    account_id: int | None,
    entered: Mapping[int, int],
) -> list[BondDraft]:
    """Every Draft due by ``day`` in the View Scope, the earliest first: maturities and coupons."""
    matured = maturity_drafts(positions, instruments, accounts, bonds, day, account_id)
    coupons = coupon_drafts(positions, instruments, accounts, bonds, day, account_id, entered)
    return sorted([*matured, *coupons], key=lambda draft: draft.due)
