"""Instrument search by ISIN, name or symbol (issue #25, spec 4.1): its results and what a chosen one fills in."""

from dataclasses import dataclass, replace
from typing import Protocol

from financial_app.domain.instruments import ISIN_PATTERN

# Yahoo's suffix of Warsaw listings; the symbol without it is the Bossa symbol
WARSAW_SUFFIX = ".WA"


class InstrumentSearchError(Exception):
    """The search could not be done; the message is shown in the UI (Polish)."""


@dataclass(frozen=True)
class SearchResult:
    """One listing found: ``symbol`` is its Yahoo symbol, ``currency`` its quote currency ("" when unknown) and
    ``isin`` the ISIN searched for ("" after a search by name or symbol)."""

    name: str
    symbol: str
    market: str
    currency: str
    isin: str = ""

    @property
    def bossa_symbol(self) -> str:
        """The Bossa symbol of a Warsaw listing, else ""."""
        return self.symbol.removesuffix(WARSAW_SUFFIX) if self.symbol.endswith(WARSAW_SUFFIX) else ""


class InstrumentSearch(Protocol):
    """A swappable search service (Yahoo now, OpenFIGI could follow); raises ``InstrumentSearchError``."""

    def search(self, query: str) -> list[SearchResult]: ...


@dataclass(frozen=True)
class FormFields:
    """The Instrument form's fields a search result can fill."""

    isin: str = ""
    quote_currency: str = ""
    market: str = ""
    yahoo: str = ""
    bossa: str = ""


def fill_empty(fields: FormFields, result: SearchResult) -> FormFields:
    """``fields`` with the empty ones taken from ``result``; values already entered (and the name) are never
    overwritten."""

    def pick(current: str, found: str) -> str:
        return current if current.strip() else found

    return replace(
        fields,
        isin=pick(fields.isin, result.isin),
        quote_currency=pick(fields.quote_currency, result.currency),
        market=pick(fields.market, result.market),
        yahoo=pick(fields.yahoo, result.symbol),
        bossa=pick(fields.bossa, result.bossa_symbol),
    )


def looks_like_isin(query: str) -> bool:
    return ISIN_PATTERN.fullmatch(query.strip().upper()) is not None
