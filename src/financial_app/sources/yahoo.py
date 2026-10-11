"""Quotes from the Yahoo chart API (spec 4.1): foreign stocks and ETFs, crypto and metals; and the Instrument search
through Yahoo search (issue #25)."""

import json
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from urllib.error import HTTPError
from urllib.parse import quote as url_quote

from financial_app.domain.instrument_search import InstrumentSearchError, SearchResult, looks_like_isin
from financial_app.domain.prices import YAHOO, PriceSourceError, Quote

API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
SEARCH_API = "https://query1.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=10&newsCount=0&listsCount=0"
# Yahoo quotes London listings in pence (GBp)
MINOR_UNITS = {"GBp": ("GBP", 100)}
# Yahoo's exchange codes shown under the name the user knows; any other shows Yahoo's own name
MARKET_NAMES = {"WSE": "GPW"}


def fetch_from_yahoo(url: str) -> str | None:
    """The response body, or None when Yahoo does not know the symbol (HTTP 404); network failures raise OSError."""
    # Yahoo refuses requests without a browser-like User-Agent
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body: bytes = response.read()
            return body.decode("utf-8")
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise


class YahooSource:
    """The Yahoo Price Source; ``fetch`` is injectable so tests run on saved responses."""

    name = YAHOO

    def __init__(self, fetch: Callable[[str], str | None] = fetch_from_yahoo) -> None:
        self.fetch = fetch

    def new_refresh(self) -> None:
        """Yahoo is asked per symbol, so nothing is kept between refreshes."""

    def quote(self, symbol: str, currency: str) -> Quote:
        """The newest Quote of ``symbol`` in ``currency``, the Instrument's quote currency.

        Only crypto is converted, at Yahoo's own rate (e.g. ``USDPLN=X``), as no PLN pair exists for most coins; any
        other currency mismatch is an error (spec 4.1).
        """
        price, source_currency, day, kind = self._latest(symbol)
        if source_currency != currency and kind == "CRYPTOCURRENCY":
            rate, _, _, _ = self._latest(f"{source_currency}{currency}=X")
            price, source_currency = price * rate, currency
        if source_currency != currency:
            raise PriceSourceError(
                f"Yahoo podaje cenę {symbol} w {source_currency}, a instrument jest notowany w {currency}."
            )
        return Quote(price, currency, day, YAHOO)

    def _latest(self, symbol: str) -> tuple[Decimal, str, date, str]:
        return _latest(self.fetch, symbol)


class YahooSearch:
    """The Instrument search through Yahoo search; ``fetch`` is injectable so tests run on saved responses."""

    def __init__(self, fetch: Callable[[str], str | None] = fetch_from_yahoo) -> None:
        self.fetch = fetch

    def search(self, query: str) -> list[SearchResult]:
        """The listings matching an ISIN, a name or a symbol, each with its quote currency from one chart request
        ("" when that fails). Results of an ISIN carry it."""
        query = query.strip()
        if not query:
            return []
        quotes = self._quotes(query)
        isin = query.upper() if looks_like_isin(query) else ""
        if isin:
            # Yahoo matches an ISIN to one listing only; the fund's other listings share its full name
            for name in dict.fromkeys(str(q["longname"]) for q in quotes if q.get("longname")):
                quotes += [q for q in self._quotes(name) if q.get("longname") == name]
        unique: dict[str, dict[str, object]] = {}
        for q in quotes:
            unique.setdefault(str(q["symbol"]), q)
        return [
            SearchResult(
                name=str(q.get("longname") or q.get("shortname") or symbol),
                symbol=symbol,
                market=MARKET_NAMES.get(str(q.get("exchange")), str(q.get("exchDisp") or q.get("exchange") or "")),
                currency=self._currency(symbol),
                isin=isin,
            )
            for symbol, q in unique.items()
        ]

    def _quotes(self, query: str) -> list[dict[str, object]]:
        try:
            body = self.fetch(SEARCH_API.format(query=url_quote(query, safe="")))
        except HTTPError as exc:
            raise InstrumentSearchError(f"Yahoo zwróciło błąd HTTP {exc.code}. Spróbuj później.") from None
        except OSError:
            raise InstrumentSearchError("Nie udało się połączyć z Yahoo. Sprawdź połączenie z internetem.") from None
        try:
            quotes = json.loads(body or "")["quotes"]
            return [q for q in quotes if isinstance(q, dict) and q.get("symbol")]
        except ValueError, KeyError, TypeError:
            raise InstrumentSearchError("Nieprawidłowa odpowiedź wyszukiwarki Yahoo.") from None

    def _currency(self, symbol: str) -> str:
        try:
            return _latest(self.fetch, symbol)[1]
        except PriceSourceError:
            return ""


def _latest(fetch: Callable[[str], str | None], symbol: str) -> tuple[Decimal, str, date, str]:
    """The last price of ``symbol``, its currency (pence as pounds), its exchange's day and its instrument type."""
    try:
        body = fetch(API.format(symbol=url_quote(symbol, safe="")))
    except HTTPError as exc:
        raise PriceSourceError(f"Yahoo zwróciło błąd HTTP {exc.code} dla {symbol}. Spróbuj później.") from None
    except OSError:
        raise PriceSourceError("Nie udało się połączyć z Yahoo. Sprawdź połączenie z internetem.") from None
    if body is None:
        raise PriceSourceError(f"Yahoo nie zna symbolu „{symbol}”.")
    try:
        meta = json.loads(body, parse_float=Decimal)["chart"]["result"][0]["meta"]
        # The exchange's own day: regularMarketTime is UTC, gmtoffset the exchange's offset from it
        day = datetime.fromtimestamp(meta["regularMarketTime"] + meta["gmtoffset"], UTC).date()
        price, currency, kind = Decimal(meta["regularMarketPrice"]), str(meta["currency"]), meta["instrumentType"]
    except ValueError, KeyError, IndexError, TypeError:
        raise PriceSourceError(f"Nieprawidłowa odpowiedź Yahoo dla {symbol}.") from None
    if currency in MINOR_UNITS:
        currency, divisor = MINOR_UNITS[currency]
        price /= divisor
    return price, currency, day, str(kind)
