"""Quotes from the Bossa JSON API (spec 4.1): GPW shares, NewConnect, ETFs and Catalyst bonds, in PLN.

Bossa serves a whole category of listings in one response, so each category is requested at most once per refresh,
however many Instruments it prices; ``new_refresh`` forgets them. Bossa quotes a Catalyst bond as a percent of its
nominal, so its Quote is that percent of the bond's nominal plus its accrued interest, a price per bond in PLN (backlog
L-23); a bond whose nominal cannot be had gets no Quote rather than a percent.
"""

import json
import urllib.request
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError

from financial_app.domain.catalyst import BondFactsSource, bond_price
from financial_app.domain.instruments import InstrumentType
from financial_app.domain.prices import BOSSA, CurrencyMismatchError, PriceSourceError, Quote
from financial_app.sources.catalyst import CatalystFacts

API = "https://bossa.pl/fl_api/API/GPW/v2/Q/C/{category}"
# Searched in this order, each only when the symbol is not in the ones before
CATEGORIES = ("_cat_shares", "_cat_nConnect", "_cat_etf", "_cat_bonds")
# The category quoting Catalyst bonds as a percent of nominal
BONDS = "_cat_bonds"
# The Instrument Type each category tells (issue #198)
INSTRUMENT_TYPES = {
    "_cat_shares": InstrumentType.STOCK,
    "_cat_nConnect": InstrumentType.STOCK,
    "_cat_etf": InstrumentType.ETF,
    BONDS: InstrumentType.BOND,
}
CURRENCY = "PLN"


def fetch_from_bossa(url: str) -> str:
    """The response body; HTTP and network failures raise OSError."""
    # Like Yahoo, Bossa may refuse requests without a browser-like User-Agent (the sheet sends one too)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        body: bytes = response.read()
        return body.decode("utf-8")


class BossaSource:
    """The Bossa Price Source; ``fetch`` and the Catalyst ``bonds`` facts are injectable so tests run on saved
    responses."""

    name = BOSSA

    def __init__(self, fetch: Callable[[str], str] = fetch_from_bossa, bonds: BondFactsSource | None = None) -> None:
        self.fetch = fetch
        self.bonds = CatalystFacts() if bonds is None else bonds
        # This refresh's categories: their Quotes by upper-case symbol, or why they could not be loaded
        self._loaded: dict[str, dict[str, Quote] | PriceSourceError] = {}
        # The category each symbol quoted so far was found in, by its key
        self._categories: dict[str, str] = {}

    def new_refresh(self) -> None:
        """Forget the categories and bond facts loaded so far, so that the next Quotes are fetched anew."""
        self._loaded = {}
        self._categories = {}
        self.bonds.new_refresh()

    def quote(self, symbol: str, currency: str) -> Quote:
        """The newest Quote of ``symbol``: Bossa's short symbol (e.g. CDR) or full one (CDPROJEKT), with or without a
        ``WSE:`` prefix as in the sheet.

        Without a trade in the session the reference price is the Quote, as in the sheet. Bossa quotes in PLN only, so
        an Instrument in another currency gets a ``CurrencyMismatchError`` carrying the PLN Quote.
        """
        if currency != CURRENCY:
            message = f"Bossa podaje ceny w {CURRENCY}, a instrument jest notowany w {currency}."
            try:
                quote = self._find(symbol)
            except PriceSourceError:
                # The currency is the reason a refresh reports, whatever else went wrong
                raise PriceSourceError(message) from None
            raise CurrencyMismatchError(message, quote)
        return self._find(symbol)

    def instrument_type_of(self, symbol: str) -> InstrumentType | None:
        """The Instrument Type told by the category ``symbol`` was quoted in this refresh; ``None`` before."""
        category = self._categories.get(_key(symbol))
        return None if category is None else INSTRUMENT_TYPES[category]

    def _find(self, symbol: str) -> Quote:
        key = _key(symbol)
        first_error = None
        for category in CATEGORIES:
            if category not in self._loaded:
                self._loaded[category] = self._load(category)
            quotes = self._loaded[category]
            if isinstance(quotes, PriceSourceError):
                first_error = first_error or quotes
            elif key in quotes:
                self._categories[key] = category
                quote = quotes[key]
                if category != BONDS:
                    return quote
                return replace(quote, price=bond_price(quote.price, self.bonds.of(key, quote.day)))
        if first_error is not None:
            raise first_error
        raise PriceSourceError(f"Bossa nie zna symbolu „{symbol}”.")

    def _load(self, category: str) -> dict[str, Quote] | PriceSourceError:
        try:
            body = self.fetch(API.format(category=category))
        except HTTPError as exc:
            return PriceSourceError(f"Bossa zwróciła błąd HTTP {exc.code}. Spróbuj później.")
        except OSError:
            return PriceSourceError("Nie udało się połączyć z Bossa. Sprawdź połączenie z internetem.")
        try:
            listings = [listing for block in json.loads(body)["_d"] for listing in block["_t"]]
        except ValueError, KeyError, TypeError:
            return PriceSourceError("Nieprawidłowa odpowiedź Bossa.")
        by_full: dict[str, Quote] = {}
        by_short: dict[str, Quote] = {}
        for listing in listings:
            quote = _quote(listing)
            if quote is not None:
                by_full[str(listing.get("_symbol")).upper()] = quote
                by_short[str(listing.get("_symbol_short")).upper()] = quote
        # The short symbol wins if it ever clashes with another listing's full one
        return by_full | by_short


def _key(symbol: str) -> str:
    """A symbol as the categories' Quotes are kept by: upper case, without a ``WSE:`` prefix."""
    return symbol.strip().upper().removeprefix("WSE:")


def _quote(listing: dict[str, Any]) -> Quote | None:
    """The listing's Quote; ``None`` for one without a positive price or a day, which never stops the others."""
    try:
        price = Decimal(str(listing.get("_quote") or listing.get("_quote_ref")))
        day = datetime.strptime(str(listing.get("_quote_date")), "%Y.%m.%d").date()
    except InvalidOperation, ValueError:
        return None
    return Quote(price, CURRENCY, day, BOSSA) if price > 0 else None
