"""Instruments and the Asset Classes they belong to (spec 3.2)."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from financial_app.domain.currencies import is_currency_code

# The sheet's Asset Classes in its order (spec 3.2): migration 0004 seeds them and clearing the portfolio restores them
DEFAULT_ASSET_CLASSES = [
    "Gotówka",
    "Akcje polskie",
    "Akcje zagraniczne",
    "Obligacje skarbowe polskie",
    "Obligacje skarbowe zagraniczne",
    "Obligacje korporacyjne polskie",
    "Obligacje korporacyjne zagraniczne",
    "Metale i surowce",
    "Kryptowaluty",
    "Waluty",
    "Inne",
    "Multi-asset",
]

# Two letters of the issuer's country, nine letters or digits and a check digit
ISIN_PATTERN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")

# A troy ounce, the unit of metal spot prices (spec 4.1)
GRAMS_PER_TROY_OUNCE = Decimal("31.1034768")


class DistributionPolicy(StrEnum):
    """Whether a fund reinvests its income or pays it out. Values are stored in the database, so never rename them."""

    ACCUMULATING = "accumulating"
    DISTRIBUTING = "distributing"

    @property
    def label(self) -> str:
        return "Akumulacja" if self is DistributionPolicy.ACCUMULATING else "Dystrybucja"


class InstrumentError(ValueError):
    """An Instrument or Asset Class field the user must correct; the message is shown in the UI (Polish)."""


@dataclass(frozen=True)
class AssetClass:
    """A saved Asset Class. Instruments refer to it by ``id``, so renaming it changes no other data."""

    id: int
    name: str


def validate_asset_class_name(name: str) -> str:
    """The Asset Class name the user typed, validated and trimmed."""
    name = name.strip()
    if not name:
        raise InstrumentError("Nazwa klasy aktywów nie może być pusta.")
    return name


@dataclass(frozen=True)
class InstrumentDraft:
    """The user-editable fields of an Instrument, validated and normalised on creation.

    ``manual_price`` is in ``quote_currency``; ``source_symbols`` maps a Price Source (``domain.prices``) to the
    Instrument's Source Symbol in it. ``isin`` is optional and not unique: each listing of a security (exchange,
    currency) is its own Instrument with the same ISIN.

    A physical metal (coins, bars) is still held in units: ``metal_grams`` is the metal weight of one unit, and its
    prices (Manual Price and Quotes) are the spot price of a troy ounce, which ``unit_price`` turns into the value of
    a unit less the ``buyback_spread_percent`` a dealer takes when buying it back (spec 4.1).

    A fund's ``ter_percent``, ``distribution_policy`` and ``domicile`` are optional details the user enters (issue #42).
    """

    name: str
    asset_class_id: int
    quote_currency: str
    market: str = ""
    manual_price: Decimal | None = None
    source_symbols: Mapping[str, str] = field(default_factory=dict)
    metal_grams: Decimal | None = None
    buyback_spread_percent: Decimal | None = None
    isin: str = ""
    ter_percent: Decimal | None = None
    distribution_policy: DistributionPolicy | None = None
    domicile: str = ""

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise InstrumentError("Nazwa instrumentu nie może być pusta.")
        currency = self.quote_currency.strip().upper()
        if not is_currency_code(currency):
            raise InstrumentError(
                f"Nieprawidłowy kod waluty: {currency or '(pusty)'}. Użyj trzyliterowego kodu, np. PLN."
            )
        if self.manual_price is not None and not self.manual_price > 0:
            raise InstrumentError("Cena ręczna musi być większa od zera.")
        if self.metal_grams is not None and not self.metal_grams > 0:
            raise InstrumentError("Waga metalu musi być większa od zera.")
        spread = self.buyback_spread_percent
        if spread is not None:
            if self.metal_grams is None:
                raise InstrumentError("Spread odkupu wymaga wagi metalu w jednostce.")
            if not 0 <= spread < 100:
                raise InstrumentError("Spread odkupu musi wynosić od 0 do mniej niż 100%.")
        if self.ter_percent is not None and not 0 <= self.ter_percent < 100:
            raise InstrumentError("TER musi wynosić od 0 do mniej niż 100%.")
        isin = self.isin.strip().upper()
        if isin and not ISIN_PATTERN.fullmatch(isin):
            raise InstrumentError(f"Nieprawidłowy ISIN: {isin}. ISIN ma 12 znaków, np. IE00B6R52259.")
        object.__setattr__(self, "isin", isin)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "quote_currency", currency)
        object.__setattr__(self, "market", self.market.strip())
        object.__setattr__(self, "domicile", self.domicile.strip())
        # A blank symbol means none in that source
        symbols = {source: symbol.strip() for source, symbol in self.source_symbols.items() if symbol.strip()}
        object.__setattr__(self, "source_symbols", symbols)

    def unit_price(self, price: Decimal) -> Decimal:
        """The value of one unit at ``price``: for a physical metal, ``price`` is the spot of a troy ounce, scaled to
        the unit's weight and less the Buyback Spread; otherwise it already is the unit price."""
        spread = self.buyback_spread_percent or Decimal(0)
        return self.unit_spot(price) * (1 - spread / 100)

    def unit_spot(self, price: Decimal) -> Decimal:
        """One unit at ``price`` without the Buyback Spread: the spot of a troy ounce scaled to the unit's metal
        weight, or ``price`` itself for any other Instrument."""
        if self.metal_grams is None:
            return price
        return price * self.metal_grams / GRAMS_PER_TROY_OUNCE


@dataclass(frozen=True)
class Instrument(InstrumentDraft):
    """A saved Instrument with the current name of its Asset Class."""

    id: int = field(kw_only=True)
    asset_class_name: str = field(kw_only=True)
