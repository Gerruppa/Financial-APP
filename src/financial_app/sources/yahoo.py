"""Quotes from the Yahoo chart API (spec 4.1): foreign stocks and ETFs, crypto and metals."""

import json
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from urllib.error import HTTPError
from urllib.parse import quote as url_quote

from financial_app.domain.prices import YAHOO, PriceSourceError, Quote

API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
# Yahoo quotes London listings in pence (GBp)
MINOR_UNITS = {"GBp": ("GBP", 100)}


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
        """The last price of ``symbol``, its currency (pence as pounds), its exchange's day and its instrument type."""
        try:
            body = self.fetch(API.format(symbol=url_quote(symbol, safe="")))
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
