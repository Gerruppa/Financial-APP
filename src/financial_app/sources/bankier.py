"""Fund and PPK Quotes from bankier.pl's fund pages (spec 4.1), the fallback for analizy.pl.

bankier.pl has no API, so the price and its day are read from the header of the fund's page: the header is found
by its ``data-symbol`` attribute, the price and day in it by their classes, so a change of the page's layout shows as
"Nieprawidłowa odpowiedź bankier.pl" and analizy.pl stays the first source (ADR-0005). bankier.pl uses the same fund
ids as analizy.pl.
"""

import re
import urllib.request
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError
from urllib.parse import quote as url_quote

from financial_app.domain.prices import BANKIER, PriceSourceError, Quote

# Investment funds first, then PPK; an unknown fund leads to the home page, without the fund's header
PAGES = ("https://www.bankier.pl/fundusze/notowania/{symbol}", "https://www.bankier.pl/ppk/notowania/{symbol}")
HEADER = '<section class="o-quotes-profile-header-box"[^>]*data-symbol="{symbol}"(.*?)</section>'
PRICE = re.compile(r'class="a-quote-item -value">([^<]+)<')
DAY = re.compile(r'class="-date">[^<]*?(\d{2}\.\d{2}\.\d{4})<')


def fetch_from_bankier(url: str) -> str | None:
    """The page, or None when bankier.pl does not have it (HTTP 404); network failures raise OSError."""
    # Like Yahoo, bankier.pl may refuse requests without a browser-like User-Agent
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body: bytes = response.read()
            return body.decode("utf-8")
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise


class BankierSource:
    """The bankier.pl Price Source; ``fetch`` is injectable so tests run on saved pages."""

    name = BANKIER

    def __init__(self, fetch: Callable[[str], str | None] = fetch_from_bankier) -> None:
        self.fetch = fetch

    def new_refresh(self) -> None:
        """bankier.pl is asked per fund, so nothing is kept between refreshes."""

    def quote(self, symbol: str, currency: str) -> Quote:
        """The newest valuation of the fund with id ``symbol`` (e.g. QRS32 or PZU60)."""
        key = symbol.strip().upper()
        header = re.compile(HEADER.format(symbol=re.escape(key)), re.S)
        first_error = None
        # A failing fund page never stops the PPK page, which may have the fund
        for page in PAGES:
            try:
                body = self.fetch(page.format(symbol=url_quote(key, safe="")))
            except HTTPError as exc:
                first_error = first_error or PriceSourceError(
                    f"bankier.pl zwrócił błąd HTTP {exc.code}. Spróbuj później."
                )
                continue
            except OSError:
                first_error = first_error or PriceSourceError(
                    "Nie udało się połączyć z bankier.pl. Sprawdź połączenie z internetem."
                )
                continue
            found = header.search(body) if body is not None else None
            if found is not None:
                return _quote_in_header(key, found.group(1), currency)
        raise first_error or PriceSourceError(f"bankier.pl nie zna funduszu „{key}”.")


def _quote_in_header(symbol: str, header: str, currency: str) -> Quote:
    """The Quote in a fund's page header, whose price reads e.g. "1 203,83 PLN" (non-breaking spaces) and day
    "Czw. 08.10.2026"."""
    price_match, day_match = PRICE.search(header), DAY.search(header)
    try:
        if price_match is None or day_match is None:
            raise ValueError
        amount, source_currency = price_match.group(1).strip().rsplit(maxsplit=1)
        price = Decimal(re.sub(r"\s", "", amount).replace(",", "."))
        day = datetime.strptime(day_match.group(1), "%d.%m.%Y").date()
    except ValueError, InvalidOperation:
        raise PriceSourceError("Nieprawidłowa odpowiedź bankier.pl.") from None
    if source_currency != currency:
        raise PriceSourceError(
            f"bankier.pl wycenia {symbol} w {source_currency}, a instrument jest notowany w {currency}."
        )
    return Quote(price, currency, day, BANKIER)
