"""Instruments and the Asset Classes they belong to (spec 3.2)."""

from dataclasses import dataclass, field
from decimal import Decimal

from financial_app.domain.currencies import is_currency_code


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

    ``manual_price`` is in ``quote_currency``; Source Symbols join with the Price Sources (Stage 2).
    """

    name: str
    asset_class_id: int
    quote_currency: str
    market: str = ""
    manual_price: Decimal | None = None

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
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "quote_currency", currency)
        object.__setattr__(self, "market", self.market.strip())


@dataclass(frozen=True)
class Instrument(InstrumentDraft):
    """A saved Instrument with the current name of its Asset Class."""

    id: int = field(kw_only=True)
    asset_class_name: str = field(kw_only=True)
