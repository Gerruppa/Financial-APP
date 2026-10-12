"""Fund and PPK Quotes from the analizy.pl API (spec 4.1), the first source for Multi-asset, Inne and added classes;
and the fund search (issue #60).

The API is undocumented (the sheet uses it too). Funds are valued once a day, so the Quote's day is often the day
before.
"""

import html
import json
import re
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from urllib.error import HTTPError
from urllib.parse import quote as url_quote

from financial_app.domain.instrument_search import InstrumentSearchError, SearchResult, looks_like_isin
from financial_app.domain.prices import ANALIZY, CurrencyMismatchError, PriceSourceError, Quote

# The fund type in the path does not change the answer, so every fund is asked for as "fio"
API = "https://www.analizy.pl/api/quotation/fio/{symbol}"
# The site's own search (checked 2026-10-11); without exactly these fields it answers with HTML or an error
SEARCH_API = (
    "https://www.analizy.pl/api/search/products?page=1&limit=20"
    "&fields=nazwa,nazwa.ngram,nazwaParasola,nazwaGrupy,firmaZarz,nazwaDawniej,searchBenchmark&keywords={query}"
)
# The kinds of products the search keeps: open-end funds, PPK and foreign funds; insurance (UFK), closed-end (FIZ)
# funds and ETFs are left out
FUND_KINDS = frozenset({"FIO", "SFIO", "PPK", "FZG"})
# The Asset Class a PPK fund belongs to; the class of any other fund depends on what it holds
PPK_CLASS = "Multi-asset"
# The search marks the words found with tags and adds a fund's former name, "(d. ...)", in a trailing span
_FORMER_NAME = re.compile(r'<span class="prevName">.*$', re.DOTALL)
_TAG = re.compile(r"<[^>]*>")


def fetch_from_analizy(url: str) -> str | None:
    """The response body, or None when analizy.pl does not know the fund (HTTP 404); network failures raise
    OSError."""
    # Like Yahoo, analizy.pl may refuse requests without a browser-like User-Agent
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
        quote = _newest(self.fetch, key)
        if quote.currency != currency:
            raise CurrencyMismatchError(
                f"analizy.pl wycenia {key} w {quote.currency}, a instrument jest notowany w {currency}.", quote
            )
        return quote


class AnalizySearch:
    """The fund and PPK search through analizy.pl; ``fetch`` is injectable so tests run on saved responses."""

    def __init__(self, fetch: Callable[[str], str | None] = fetch_from_analizy) -> None:
        self.fetch = fetch

    def search(self, query: str) -> list[SearchResult]:
        """The funds matching a name, a Fund Code with its series or (for foreign funds) an ISIN, each with its quote
        currency from its newest valuation ("" when that fails) and its Fund Code. Results of an ISIN carry it."""
        query = query.strip()
        if not query:
            return []
        funds = [product for product in self._products(query) if product[2] in FUND_KINDS]
        # One quotation request per fund, side by side so a dozen of them do not keep the user waiting
        with ThreadPoolExecutor(max_workers=8) as pool:
            currencies = list(pool.map(self._currency, [code for code, _, _, _ in funds]))
        searched = query.upper() if looks_like_isin(query) else ""
        return [
            SearchResult(
                name=name,
                symbol=code,
                market="",
                currency=currency,
                source_symbols={ANALIZY: code},
                isin=searched or isin,
                asset_class=PPK_CLASS if kind == "PPK" else "",
                fund=True,
            )
            for (code, name, kind, isin), currency in zip(funds, currencies, strict=True)
        ]

    def _products(self, query: str) -> list[tuple[str, str, str, str]]:
        """Each product found: its Fund Code, its plain name, its kind (FIO, PPK, UFK, ...) and its ISIN ("" when
        the search gives none, as it has so far)."""
        try:
            body = self.fetch(SEARCH_API.format(query=url_quote(query, safe="")))
        except HTTPError as exc:
            raise InstrumentSearchError(f"analizy.pl zwróciło błąd HTTP {exc.code}. Spróbuj później.") from None
        except OSError:
            raise InstrumentSearchError(
                "Nie udało się połączyć z analizy.pl. Sprawdź połączenie z internetem."
            ) from None
        try:
            products = json.loads(body or "")["products"]
            return [
                (str(p["kod"]), _plain(str(p["nazwa"])), str(p["kodRodzaju"]), str(p.get("isin") or "").upper())
                for p in products
            ]
        except ValueError, KeyError, TypeError:
            raise InstrumentSearchError("Nieprawidłowa odpowiedź wyszukiwarki analizy.pl.") from None

    def _currency(self, code: str) -> str:
        try:
            return _newest(self.fetch, code).currency
        except PriceSourceError:
            return ""


def _plain(name: str) -> str:
    """A found fund's name without the search's markup and its former name."""
    return " ".join(html.unescape(_TAG.sub("", _FORMER_NAME.sub("", name))).split())


def _newest(fetch: Callable[[str], str | None], key: str) -> Quote:
    """The newest valuation of the fund ``key``, in the fund's own currency."""
    try:
        body = fetch(API.format(symbol=url_quote(key, safe="")))
    except HTTPError as exc:
        raise PriceSourceError(f"analizy.pl zwróciło błąd HTTP {exc.code}. Spróbuj później.") from None
    except OSError:
        raise PriceSourceError("Nie udało się połączyć z analizy.pl. Sprawdź połączenie z internetem.") from None
    if body is None:
        raise PriceSourceError(f"analizy.pl nie zna funduszu „{key}”.")
    try:
        data = json.loads(body, parse_float=Decimal)
        # The first series is the fund's own valuation; the second, when filled, adds back paid dividends
        series = data["series"][0]
        currency = str(series["currency"])
        valuations = [(date.fromisoformat(p["date"]), Decimal(p["value"])) for p in series["price"]]
        # The newest valuation, whatever order they come in; a fund without a positive one has no Quote
        day, price = max(valuations, default=(date.min, Decimal(0)))
        if price <= 0:
            raise PriceSourceError(f"analizy.pl nie ma wyceny funduszu „{key}”.")
    except ValueError, KeyError, IndexError, TypeError:
        raise PriceSourceError("Nieprawidłowa odpowiedź analizy.pl.") from None
    return Quote(price, currency, day, ANALIZY)
