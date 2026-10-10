"""Quotes from the Bossa JSON API (spec 4.1): GPW shares, NewConnect, ETFs and Catalyst bonds, in PLN.

Bossa serves a whole category in one response, so each category is requested once per refresh, however many
Instruments it prices: a loaded category is reused for ``FRESH_FOR`` seconds.
"""

import json
import time
import urllib.request
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError

from financial_app.domain.prices import BOSSA, PriceSourceError, Quote

API = "https://bossa.pl/fl_api/API/GPW/v2/Q/C/{category}"
# Searched in this order, each only when the symbol is not in the ones before
CATEGORIES = ("_cat_shares", "_cat_nConnect", "_cat_etf", "_cat_bonds")
# Long enough for one refresh, short enough that the next one fetches new prices
FRESH_FOR = 5 * 60
CURRENCY = "PLN"


def fetch_from_bossa(url: str) -> str:
    """The response body; HTTP and network failures raise OSError."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        body: bytes = response.read()
        return body.decode("utf-8")


class BossaSource:
    """The Bossa Price Source; ``fetch`` and ``clock`` (seconds) are injectable so tests run on saved responses."""

    name = BOSSA

    def __init__(self, fetch: Callable[[str], str] = fetch_from_bossa, clock: Callable[[], float] = time.monotonic):
        self.fetch = fetch
        self.clock = clock
        # Category -> (when it was loaded, its Quotes by upper-case symbol)
        self._loaded: dict[str, tuple[float, dict[str, Quote]]] = {}

    def quote(self, symbol: str, currency: str) -> Quote:
        """The newest Quote of ``symbol``, Bossa's short symbol (e.g. CDR) or full one (CDPROJEKT).

        Without a trade in the session the reference price is the Quote, as in the sheet.
        """
        if currency != CURRENCY:
            raise PriceSourceError(f"Bossa podaje ceny w {CURRENCY}, a instrument jest notowany w {currency}.")
        key = symbol.strip().upper().removeprefix("WSE:")
        errors = []
        for category in CATEGORIES:
            try:
                quotes = self._category(category)
            except PriceSourceError as error:
                errors.append(error)
                continue
            if key in quotes:
                return quotes[key]
        if errors:
            raise errors[0]
        raise PriceSourceError(f"Bossa nie zna symbolu „{symbol}”.")

    def _category(self, category: str) -> dict[str, Quote]:
        now = self.clock()
        if category in self._loaded and now - self._loaded[category][0] < FRESH_FOR:
            return self._loaded[category][1]
        try:
            body = self.fetch(API.format(category=category))
        except HTTPError as exc:
            raise PriceSourceError(f"Bossa zwróciła błąd HTTP {exc.code}. Spróbuj później.") from None
        except OSError:
            raise PriceSourceError("Nie udało się połączyć z Bossa. Sprawdź połączenie z internetem.") from None
        quotes = _parse(body)
        self._loaded[category] = (now, quotes)
        return quotes


def _parse(body: str) -> dict[str, Quote]:
    """Each listing's Quote by its full and short symbol; the short one wins if they ever clash."""
    by_full: dict[str, Quote] = {}
    by_short: dict[str, Quote] = {}
    try:
        for block in json.loads(body)["_d"]:
            for listing in block["_t"]:
                price = listing["_quote"] or listing["_quote_ref"]
                if not price:
                    continue
                day = datetime.strptime(listing["_quote_date"], "%Y.%m.%d").date()
                quote = Quote(Decimal(str(price)), CURRENCY, day, BOSSA)
                by_full[str(listing["_symbol"]).upper()] = quote
                by_short[str(listing["_symbol_short"]).upper()] = quote
    except ValueError, KeyError, TypeError, InvalidOperation:
        raise PriceSourceError("Nieprawidłowa odpowiedź Bossa.") from None
    return by_full | by_short
