"""The nominal and accrued interest of Catalyst bonds (backlog L-23 and L-24, spec 4), which turn Bossa's percent of
nominal into a price per bond.

gpwcatalyst.pl lists every bond quoted on Catalyst with its nominal and the interest accrued on one bond, in PLN; the
indexed treasury IZ bonds take both from the MF table of indexation coefficients on gov.pl instead, which gives each
day of the month. Each page is fetched at most once a refresh (``new_refresh`` forgets them), however many bonds it
serves, and the sheet reads the same pages.
"""

import html
import re
import urllib.request
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError

from financial_app.domain.catalyst import IZ_SERIES, BondFacts, IndexationDay, indexed_facts, is_indexed
from financial_app.domain.prices import PriceSourceError

CATALYST_LISTING = "https://gpwcatalyst.pl/o-instrumentach-instrumenty-notowane"
INDEXATION_PAGE = "https://www.gov.pl/web/finanse/wspolczynniki-indeksacji2"

# Bossa quotes Catalyst in PLN only, so the table of bonds in EUR is left out
_PLN_TABLE = re.compile(r'<table[^>]*id="bs-instrument-PLN".*?</table>', re.S)
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_SYMBOL = re.compile(r'o-instrumentach-instrument\?nazwa=([^"]+)"')
_NOMINAL = re.compile(r'class="col8"[^>]*>(.*?)</td>', re.S)
_ACCRUED = re.compile(r'class="col10"[^>]*>(.*?)</td>', re.S)
_HEADER = re.compile(r"<th[^>]*>(.*?)</th>", re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG = re.compile(r"<[^>]+>")
_DAY = re.compile(r"\d{2}\.\d{2}\.\d{4}")


def fetch_page(url: str) -> str:
    """The page at ``url``; HTTP and network failures raise OSError."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        body: bytes = response.read()
        # gpwcatalyst.pl mixes encodings on one page; the numbers and symbols read are ASCII either way
        return body.decode("utf-8", errors="replace")


class CatalystFacts:
    """Each Catalyst bond's nominal and accrued interest; ``fetch`` is injectable for tests."""

    def __init__(self, fetch: Callable[[str], str] = fetch_page) -> None:
        self.fetch = fetch
        self._listing: dict[str, BondFacts] | PriceSourceError | None = None
        self._indexation: dict[str, list[IndexationDay]] | PriceSourceError | None = None

    def new_refresh(self) -> None:
        """Forget the pages loaded so far, so that the next facts are fetched anew."""
        self._listing = None
        self._indexation = None

    def of(self, symbol: str, day: date) -> BondFacts:
        """The bond's facts for its Quote of ``day``: an IZ bond's of that day from gov.pl while it has them, any
        other's from gpwcatalyst.pl, which lists today's only.

        Raises PriceSourceError when they cannot be had.
        """
        key = symbol.strip().upper()
        if is_indexed(key):
            if self._indexation is None:
                self._indexation = self._load(INDEXATION_PAGE, "gov.pl", parse_indexation)
            if not isinstance(self._indexation, PriceSourceError):
                facts = indexed_facts(self._indexation.get(key, []), day)
                if facts is not None:
                    return facts
        if self._listing is None:
            self._listing = self._load(CATALYST_LISTING, "gpwcatalyst.pl", parse_catalyst_listing)
        if isinstance(self._listing, PriceSourceError):
            raise self._listing
        if key not in self._listing:
            raise PriceSourceError(f"gpwcatalyst.pl nie podaje wartości nominalnej obligacji „{symbol}”.")
        return self._listing[key]

    def _load[T](self, url: str, site: str, parse: Callable[[str], T]) -> T | PriceSourceError:
        try:
            return parse(self.fetch(url))
        except HTTPError as exc:
            return PriceSourceError(f"{site} zwrócił błąd HTTP {exc.code}. Spróbuj później.")
        except OSError:
            return PriceSourceError(f"Nie udało się połączyć z {site}. Sprawdź połączenie z internetem.")
        except PriceSourceError as exc:
            return exc


def parse_catalyst_listing(page: str) -> dict[str, BondFacts]:
    """The nominal and accrued interest of each bond in PLN on the "Instrumenty notowane" page, by upper-case symbol;
    a row without them is left out. Raises PriceSourceError when the page has no such table."""
    table = _PLN_TABLE.search(page)
    if table is None:
        raise PriceSourceError("Nieprawidłowa strona gpwcatalyst.pl: brak tabeli obligacji; strona mogła się zmienić.")
    bonds = {}
    for row in _ROW.findall(table[0]):
        symbol, nominal, accrued = _SYMBOL.search(row), _NOMINAL.search(row), _ACCRUED.search(row)
        if symbol is None or nominal is None or accrued is None:
            continue
        try:
            bonds[symbol[1].strip().upper()] = BondFacts(_number(nominal[1]), _number(accrued[1]))
        except InvalidOperation:
            continue
    return bonds


def parse_indexation(page: str) -> dict[str, list[IndexationDay]]:
    """Each IZ bond's indexation coefficient and accrued interest by day, in date order, from the gov.pl table.

    The table's header names the series; each row holds one or two days (a column of days per month), each followed
    by a coefficient and the interest per series. Raises PriceSourceError when the page has no such table.
    """
    series: list[str] = []
    for header in _HEADER.findall(page):
        name = _text(header)
        if IZ_SERIES.fullmatch(name) and name not in series:
            series.append(name)
    if not series:
        raise PriceSourceError("Nieprawidłowa strona gov.pl: brak tabeli współczynników indeksacji.")
    days: dict[str, list[IndexationDay]] = {name: [] for name in series}
    block = 1 + 2 * len(series)
    for row in _ROW.findall(page):
        cells = [_text(cell) for cell in _CELL.findall(row)]
        for start in range(0, len(cells) - block + 1, block):
            if not _DAY.fullmatch(cells[start]):
                continue
            day = datetime.strptime(cells[start], "%d.%m.%Y").date()
            for index, name in enumerate(series):
                try:
                    coefficient, accrued = cells[start + 1 + 2 * index], cells[start + 2 + 2 * index]
                    days[name].append(IndexationDay(day, _number(coefficient), _number(accrued)))
                except InvalidOperation:
                    continue
    return {name: sorted(values, key=lambda value: value.day) for name, values in days.items()}


def _text(cell: str) -> str:
    return html.unescape(_TAG.sub("", cell)).strip()


def _number(text: str) -> Decimal:
    """A Polish number such as "1 077,07" (spaces as thousands separators); raises InvalidOperation otherwise."""
    cleaned = re.sub(r"\s", "", _text(text)).replace(",", ".")
    if not cleaned:
        raise InvalidOperation(text)
    return Decimal(cleaned)
