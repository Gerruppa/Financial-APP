"""Fund and PPK Quotes from the analizy.pl API (spec 4.1), the first source for Multi-asset, Inne and added classes.

The API is undocumented (the sheet uses it too). Funds are valued once a day, so the Quote's day is often the day
before.
"""

import json
import urllib.request
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from urllib.error import HTTPError
from urllib.parse import quote as url_quote

from financial_app.domain.prices import ANALIZY, PriceSourceError, Quote

# The fund type in the path does not change the answer, so every fund is asked for as "fio"
API = "https://www.analizy.pl/api/quotation/fio/{symbol}"


def fetch_from_analizy(url: str) -> str | None:
    """The response body, or None when analizy.pl does not know the fund (HTTP 404); network failures raise
    OSError."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body: bytes = response.read()
            return body.decode("utf-8")
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise


class AnalizySource:
    """The analizy.pl Price Source; ``fetch`` is injectable so tests run on saved responses."""

    name = ANALIZY

    def __init__(self, fetch: Callable[[str], str | None] = fetch_from_analizy) -> None:
        self.fetch = fetch

    def new_refresh(self) -> None:
        """analizy.pl is asked per fund, so nothing is kept between refreshes."""

    def quote(self, symbol: str, currency: str) -> Quote:
        """The newest valuation of the fund with id ``symbol`` (as in its analizy.pl address, e.g. PZU60)."""
        key = symbol.strip().upper()
        try:
            body = self.fetch(API.format(symbol=url_quote(key, safe="")))
        except HTTPError as exc:
            raise PriceSourceError(f"analizy.pl zwróciło błąd HTTP {exc.code}. Spróbuj później.") from None
        except OSError:
            raise PriceSourceError("Nie udało się połączyć z analizy.pl. Sprawdź połączenie z internetem.") from None
        if body is None:
            raise PriceSourceError(f"analizy.pl nie zna funduszu „{key}”.")
        try:
            data = json.loads(body, parse_float=Decimal)
            # The first series is the fund's own valuation; the second, when filled, adds back paid dividends
            prices = data["series"][0]["price"]
            source_currency = str(data["currency"])
            if not prices:
                raise PriceSourceError(f"analizy.pl nie ma wyceny funduszu „{key}”.")
            price, day = Decimal(prices[-1]["value"]), date.fromisoformat(prices[-1]["date"])
        except ValueError, KeyError, IndexError, TypeError:
            raise PriceSourceError("Nieprawidłowa odpowiedź analizy.pl.") from None
        if source_currency != currency:
            raise PriceSourceError(
                f"analizy.pl wycenia {key} w {source_currency}, a instrument jest notowany w {currency}."
            )
        return Quote(price, currency, day, ANALIZY)
