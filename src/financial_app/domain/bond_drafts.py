"""Maturity and Rollover as Drafts (spec 3.4.1, L-6): a Lot of a Bond Series still held on or after its maturity has not
been redeemed in the app yet, so it shows in the Obligacje tab's "Do zatwierdzenia" list.

Drafts are computed from the Lots, never stored: confirming one saves an ordinary Sell of that Lot on its maturity day
(at one bond's maturity value, no fee, the Account's Tax Regime's tax withheld), and a Rollover adds the Buy of a new
Series on the same day at its Rollover price. Once saved, the Lot is gone and so is the Draft.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account, tax_regime_for
from financial_app.domain.bond_redemption import EarlyRedemption, early_redemption
from financial_app.domain.bond_valuation import BondData
from financial_app.domain.bonds import FAMILY_TYPES, BondType, bond_type_of, maturity, series_name
from financial_app.domain.formatting import format_quantity
from financial_app.domain.instruments import Instrument
from financial_app.domain.lots import Lot, Position
from financial_app.domain.transactions import TransactionDraft, TransactionError, TransactionType, buy_or_sell

# The types a Rollover may buy: any but the family bonds, which only the 800+ benefit buys
ROLLOVER_TYPES = tuple(bond_type for bond_type in BondType if bond_type not in FAMILY_TYPES)


@dataclass(frozen=True)
class MaturityDraft:
    """A ``lot`` of a Bond Series on ``account`` that matured on ``maturity`` and is still held. ``redemption`` is what
    redeeming all its bonds that day pays (``None`` while the Series has no value, so it is entered by hand)."""

    account: Account
    instrument: Instrument
    bond_type: BondType
    lot: Lot
    maturity: date
    redemption: EarlyRedemption | None

    def rollover_series(self, bond_type: BondType) -> str:
        """The Series of ``bond_type`` a Rollover buys: the one sold in the month the Lot matures."""
        return series_name(bond_type, self.maturity)

    def redemption_transaction(self) -> TransactionDraft:
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
