"""Quotes from the Yahoo chart API (spec 4.1): foreign stocks and ETFs, crypto and metals; and the Instrument search
through Yahoo search (issue #25)."""

import json
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from urllib.error import HTTPError
from urllib.parse import quote as url_quote

from financial_app.domain.instrument_search import FoundListing, InstrumentSearchError, looks_like_isin
from financial_app.domain.instruments import CRYPTO_CLASS, InstrumentType
from financial_app.domain.prices import BOSSA, YAHOO, YAHOO_HISTORY, CurrencyMismatchError, PriceSourceError, Quote

API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
HISTORY_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={start}&period2={end}&interval=1d"
SEARCH_API = "https://query1.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=10&newsCount=0&listsCount=0"
# Yahoo quotes London listings in pence (GBp)
MINOR_UNITS = {"GBp": ("GBP", 100)}
# Yahoo's exchange codes shown under the name the user knows; any other shows Yahoo's own name
MARKET_NAMES = {"WSE": "GPW"}
# Yahoo's suffix of Warsaw listings; the symbol without it is the Bossa symbol
WARSAW_SUFFIX = ".WA"
# The Asset Class of a listing by Yahoo's quoteType (stocks also by their market, in asset_class); an ETF's class
# depends on what it holds, so it and any other type get none
ASSET_CLASSES = {"CRYPTOCURRENCY": CRYPTO_CLASS, "FUTURE": "Metale i surowce", "MUTUALFUND": "Inne"}
# The Instrument Type each of Yahoo's quoteTypes tells (issue #198); any other tells none
INSTRUMENT_TYPES = {
    "ETF": InstrumentType.ETF,
    "EQUITY": InstrumentType.STOCK,
    "CRYPTOCURRENCY": InstrumentType.CRYPTO,
    "MUTUALFUND": InstrumentType.FUND,
}
# Yahoo's quoteTypes of funds, whose ISIN tells their domicile and name their distribution policy
FUND_TYPES = frozenset({"ETF", "MUTUALFUND"})


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
        # The instrumentType of each symbol quoted so far, upper case
        self._kinds: dict[str, str] = {}

    def new_refresh(self) -> None:
        """Yahoo is asked per symbol, so no Quote is kept between refreshes; the instrument types are forgotten."""
        self._kinds = {}

    def instrument_type_of(self, symbol: str) -> InstrumentType | None:
        """The Instrument Type told by the instrumentType of a symbol quoted this refresh (#198); ``None`` before."""
        return INSTRUMENT_TYPES.get(self._kinds.get(symbol.strip().upper(), ""))

    def quote(self, symbol: str, currency: str) -> Quote:
        """The newest Quote of ``symbol`` in ``currency``, the Instrument's quote currency.

        Only crypto is converted, at Yahoo's own rate (e.g. ``USDPLN=X``), as no PLN pair exists for most coins; any
        other currency mismatch is an error (spec 4.1).
        """
        price, source_currency, day, kind = _latest(self.fetch, symbol)
        self._kinds[symbol.strip().upper()] = kind
        if source_currency != currency and kind == "CRYPTOCURRENCY":
            rate, _, _, _ = _latest(self.fetch, f"{source_currency}{currency}=X")
            price, source_currency = price * rate, currency
        if source_currency != currency:
            raise CurrencyMismatchError(
                f"Yahoo podaje cenę {symbol} w {source_currency}, a instrument jest notowany w {currency}.",
                Quote(price, source_currency, day, YAHOO),
            )
        return Quote(price, currency, day, YAHOO)

    def history(self, symbol: str, currency: str, first: date, last: date) -> list[Quote]:
        """The daily closes of ``symbol`` from ``first`` to ``last``, oldest first, for History (ADR-0006).

        ``close`` is split-adjusted only; ``adjclose`` would also take out the Dividends, which History counts from
        the Transactions. A currency other than ``currency`` is an error; days without a close are left out.
        """
        start = int(datetime.combine(first, time(), UTC).timestamp())
        end = int(datetime.combine(last + timedelta(days=1), time(), UTC).timestamp())
        url = HISTORY_API.format(symbol=url_quote(symbol, safe=""), start=start, end=end)
        body = _get(self.fetch, url, PriceSourceError, f" dla {symbol}")
        if body is None:
            raise PriceSourceError(f"Yahoo nie zna symbolu „{symbol}”.")
        try:
            result = json.loads(body, parse_float=Decimal)["chart"]["result"][0]
            meta = result["meta"]
            source_currency, offset = str(meta["currency"]), int(meta["gmtoffset"])
            stamps = result.get("timestamp") or []
            closes = result["indicators"]["quote"][0]["close"] if stamps else []
        except ValueError, KeyError, IndexError, TypeError:
            raise PriceSourceError(f"Nieprawidłowa odpowiedź Yahoo dla {symbol}.") from None
        divisor = 1
        if source_currency in MINOR_UNITS:
            source_currency, divisor = MINOR_UNITS[source_currency]
        if source_currency != currency:
            raise PriceSourceError(
                f"Yahoo podaje historię {symbol} w {source_currency}, a instrument jest notowany w {currency}."
            )
        quotes = {}
        for stamp, close in zip(stamps, closes, strict=False):
            day = datetime.fromtimestamp(stamp + offset, UTC).date()
            if close is not None and first <= day <= last:
                quotes[day] = Quote(Decimal(close) / divisor, currency, day, YAHOO_HISTORY)
        return list(quotes.values())


class YahooSearch:
    """The Instrument search through Yahoo search; ``fetch`` is injectable so tests run on saved responses."""

    def __init__(self, fetch: Callable[[str], str | None] = fetch_from_yahoo) -> None:
        self.fetch = fetch

    def search(self, query: str) -> list[FoundListing]:
        """The listings matching an ISIN, a name or a symbol, each with its quote currency from one chart request
        ("" when that fails) and its Yahoo symbol, plus the Bossa one of a Warsaw listing. Results of an ISIN carry
        it."""
        query = query.strip()
        if not query:
            return []
        quotes = self._quotes(query)
        isin = query.upper() if looks_like_isin(query) else ""
        if isin:
            # Yahoo matches an ISIN to one listing only; the fund's other listings share its full name
            for name in dict.fromkeys(str(listing["longname"]) for listing in quotes if listing.get("longname")):
                quotes += [listing for listing in self._quotes(name) if listing.get("longname") == name]
        listings: dict[str, dict[str, object]] = {}
        for listing in quotes:
            listings.setdefault(str(listing["symbol"]), listing)
        # One chart request per listing, side by side so a dozen of them do not keep the user waiting
        with ThreadPoolExecutor(max_workers=8) as pool:
            currencies = list(pool.map(self._currency, listings))
        return [
            FoundListing(
                name=str(listing.get("longname") or listing.get("shortname") or symbol),
                symbol=symbol,
                market=_market(listing),
                currency=currency,
                source_symbols=_source_symbols(symbol),
                isin=isin,
                asset_class=_asset_class(symbol, listing),
                fund=listing.get("quoteType") in FUND_TYPES,
                instrument_type=INSTRUMENT_TYPES.get(str(listing.get("quoteType") or "")),
            )
            for (symbol, listing), currency in zip(listings.items(), currencies, strict=True)
        ]

    def _quotes(self, query: str) -> list[dict[str, object]]:
        body = _get(self.fetch, SEARCH_API.format(query=url_quote(query, safe="")), InstrumentSearchError, "")
        try:
            quotes = json.loads(body or "")["quotes"]
            return [listing for listing in quotes if isinstance(listing, dict) and listing.get("symbol")]
        except ValueError, KeyError, TypeError:
            raise InstrumentSearchError("Nieprawidłowa odpowiedź wyszukiwarki Yahoo.") from None

    def _currency(self, symbol: str) -> str:
        try:
            return _latest(self.fetch, symbol)[1]
        except PriceSourceError:
            return ""


def _market(listing: dict[str, object]) -> str:
    exchange = str(listing.get("exchange") or "")
    return MARKET_NAMES.get(exchange, str(listing.get("exchDisp") or exchange))


def _asset_class(symbol: str, listing: dict[str, object]) -> str:
    kind = str(listing.get("quoteType") or "")
    if kind == "EQUITY":
        return "Akcje polskie" if symbol.endswith(WARSAW_SUFFIX) else "Akcje zagraniczne"
    return ASSET_CLASSES.get(kind, "")


def _source_symbols(symbol: str) -> dict[str, str]:
    """The Source Symbols a Yahoo listing gives: its own, and the Bossa one of a Warsaw listing."""
    if symbol.endswith(WARSAW_SUFFIX):
        return {YAHOO: symbol, BOSSA: symbol.removesuffix(WARSAW_SUFFIX)}
    return {YAHOO: symbol}


def _get(fetch: Callable[[str], str | None], url: str, error: type[Exception], subject: str) -> str | None:
    """The body at ``url``; HTTP and network failures become ``error`` with a Polish message naming ``subject``
    (e.g. " dla AAPL")."""
    try:
        return fetch(url)
    except HTTPError as exc:
        raise error(f"Yahoo zwróciło błąd HTTP {exc.code}{subject}. Spróbuj później.") from None
    except OSError:
        raise error("Nie udało się połączyć z Yahoo. Sprawdź połączenie z internetem.") from None


def _latest(fetch: Callable[[str], str | None], symbol: str) -> tuple[Decimal, str, date, str]:
    """The last price of ``symbol``, its currency (pence as pounds), its exchange's day and its instrument type."""
    body = _get(fetch, API.format(symbol=url_quote(symbol, safe="")), PriceSourceError, f" dla {symbol}")
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
