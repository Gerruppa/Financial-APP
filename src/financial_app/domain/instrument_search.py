"""Instrument search by ISIN, name or symbol (issue #25, spec 4.1): its results and what a chosen one fills in."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from financial_app.domain.instruments import ISIN_PATTERN


class InstrumentSearchError(Exception):
    """The search could not be done; the message is shown in the UI (Polish)."""


@dataclass(frozen=True)
class SearchResult:
    """One listing found: ``symbol`` is the ticker the search service shows, ``source_symbols`` the Source Symbols
    it gives (Price Source key to symbol, ``domain.prices``), ``currency`` its quote currency ("" when unknown),
    ``isin`` the ISIN searched for ("" after a search by name or symbol, as Yahoo returns no ISINs) and
    ``asset_class`` the name of the Asset Class it belongs to ("" when its kind does not tell, e.g. an ETF)."""

    name: str
    symbol: str
    market: str
    currency: str
    source_symbols: Mapping[str, str] = field(default_factory=dict)
    isin: str = ""
    asset_class: str = ""


class InstrumentSearch(Protocol):
    """A swappable search service (Yahoo now, OpenFIGI could follow); raises ``InstrumentSearchError``."""

    def search(self, query: str) -> list[SearchResult]: ...


@dataclass(frozen=True)
class FormFields:
    """The Instrument form's fields a search result can fill; ``source_symbols`` as in ``InstrumentDraft`` and
    ``asset_class`` the chosen Asset Class's name."""

    isin: str = ""
    quote_currency: str = ""
    market: str = ""
    source_symbols: Mapping[str, str] = field(default_factory=dict)
    asset_class: str = ""


def fill_empty(fields: FormFields, result: SearchResult) -> FormFields:
    """``fields`` with the empty ones taken from ``result``; values already entered (and the name) are never
    overwritten."""

    def pick(current: str, found: str) -> str:
        return current if current.strip() else found

    symbols = dict(fields.source_symbols)
    for source, symbol in result.source_symbols.items():
        symbols[source] = pick(symbols.get(source, ""), symbol)
    return FormFields(
        isin=pick(fields.isin, result.isin),
        quote_currency=pick(fields.quote_currency, result.currency),
        market=pick(fields.market, result.market),
        source_symbols=symbols,
        asset_class=pick(fields.asset_class, result.asset_class),
    )


def looks_like_isin(query: str) -> bool:
    """Whether ``query`` has the shape of an ISIN, so its results can carry it."""
    return ISIN_PATTERN.fullmatch(query.strip().upper()) is not None
