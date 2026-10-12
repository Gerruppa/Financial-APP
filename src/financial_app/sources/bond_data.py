"""The bond data sources of Stage 3 (spec 3.4.1): the MF file of retail bonds, GUS CPI and the NBP reference rate.

Each is fetched with the price refresh at most once a day (``refresh_bond_data``) into SQLite, replacing the copy kept
there; a failure keeps the last copy and is shown in the header. All three are files the institutions publish for
download, found by their links (ADR-0005): the MF file through its page on gov.pl, the GUS CSV through its page on
stat.gov.pl, the NBP rates at a fixed address.
"""

import csv
import io
import re
import urllib.request
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.error import HTTPError

import xlrd
from sqlalchemy import Engine
from xlrd.biffh import XLRDError

from financial_app.domain.bonds import BondDataError, BondType, CpiReading, ReferenceRate, SeriesTerms
from financial_app.persistence.bond_data import (
    GUS as GUS,
)
from financial_app.persistence.bond_data import (
    MF as MF,
)
from financial_app.persistence.bond_data import (
    NBP_REFERENCE as NBP_REFERENCE,
)
from financial_app.persistence.bond_data import (
    BondDataStatus,
    bond_data_statuses,
    mark_bond_data,
    save_cpi,
    save_reference_rates,
    save_series_terms,
)

BOND_DATA_NAMES = {MF: "Plik MF (obligacje)", GUS: "Inflacja CPI (GUS)", NBP_REFERENCE: "Stopa referencyjna NBP"}

MF_PAGE = "https://www.gov.pl/web/finanse/obligacje-detaliczne1"
MF_HOST = "https://www.gov.pl"
GUS_PAGE = (
    "https://stat.gov.pl/obszary-tematyczne/ceny-handel/wskazniki-cen/"
    "wskazniki-cen-towarow-i-uslug-konsumpcyjnych-pot-inflacja-/"
    "miesieczne-wskazniki-cen-towarow-i-uslug-konsumpcyjnych-od-1982-roku/"
)
GUS_HOST = "https://stat.gov.pl"
NBP_RATES = "https://static.nbp.pl/dane/stopy/stopy_procentowe_archiwum.xml"

# The MF page lists several attachments; the bond data is the one with this name
MF_LINK = re.compile(
    r'<a class="file-download" href="(/attachment/[^"]+)"(?:(?!</a>).)*?obligacji\s+detalicznych', re.S
)
GUS_LINK = re.compile(r"""Pobranie CSV[^>]*?href="([^"]+\.csv)\"""", re.S)
SERIES = re.compile(r"[A-Z]{3}\d{4}")
YEAR_ON_YEAR = "Analogiczny miesiąc poprzedniego roku = 100"
MONTH_ON_MONTH = "Poprzedni miesiąc = 100"


def download(url: str) -> bytes:
    """The body at ``url``; network failures and HTTP errors raise OSError."""
    # gov.pl and stat.gov.pl may refuse requests without a browser-like User-Agent
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        body: bytes = response.read()
        return body


class MfBondFile:
    """Every retail Bond Series with its rates from the MF file "Dane dotyczące obligacji detalicznych"."""

    def __init__(self, fetch: Callable[[str], bytes] = download) -> None:
        self.fetch = fetch

    def series(self) -> list[SeriesTerms]:
        page = _get(self.fetch, MF_PAGE, "strony MF z obligacjami").decode("utf-8", errors="replace")
        link = MF_LINK.search(page)
        if link is None:
            raise BondDataError("Nie znaleziono pliku z danymi obligacji na stronie MF; strona mogła się zmienić.")
        return parse_mf_file(_get(self.fetch, MF_HOST + link[1], "pliku MF z danymi obligacji"))


class GusCpi:
    """The monthly CPI indices from the GUS table "Miesięczne wskaźniki cen towarów i usług konsumpcyjnych"."""

    def __init__(self, fetch: Callable[[str], bytes] = download) -> None:
        self.fetch = fetch

    def readings(self) -> list[CpiReading]:
        page = _get(self.fetch, GUS_PAGE, "strony GUS ze wskaźnikami cen").decode("utf-8", errors="replace")
        link = GUS_LINK.search(page)
        if link is None:
            raise BondDataError("Nie znaleziono pliku CSV ze wskaźnikami cen na stronie GUS; strona mogła się zmienić.")
        return parse_gus_csv(_get(self.fetch, GUS_HOST + link[1], "pliku CSV GUS ze wskaźnikami cen"))


class NbpReferenceRates:
    """Every NBP reference rate since 1998 from the NBP archive of interest rates."""

    def __init__(self, fetch: Callable[[str], bytes] = download) -> None:
        self.fetch = fetch

    def rates(self) -> list[ReferenceRate]:
        return parse_nbp_rates(_get(self.fetch, NBP_RATES, "stóp procentowych NBP"))


def _get(fetch: Callable[[str], bytes], url: str, what: str) -> bytes:
    try:
        return fetch(url)
    except HTTPError as error:
        raise BondDataError(f"Serwer zwrócił błąd {error.code} przy pobieraniu {what}.") from None
    except OSError:
        raise BondDataError(f"Nie udało się pobrać {what}. Sprawdź połączenie z internetem.") from None


def parse_mf_file(content: bytes) -> list[SeriesTerms]:
    """The Series of every type in ``BondType`` from the MF file (an Excel 97 .xls), each type on its own sheet."""
    try:
        book = xlrd.open_workbook(file_contents=content)
    except XLRDError, ValueError:
        raise BondDataError("Plik MF z danymi obligacji jest nieczytelny.") from None
    series: list[SeriesTerms] = []
    for bond_type in BondType:
        try:
            sheet = book.sheet_by_name(bond_type.value)
        except XLRDError:
            raise BondDataError(f"W pliku MF brak zakładki {bond_type.value}.") from None
        series += _parse_sheet(sheet, book.datemode)
    return series


def _parse_sheet(sheet: xlrd.sheet.Sheet, datemode: Literal[0, 1]) -> list[SeriesTerms]:
    """A type's sheet: a header row (with "Seria"), on most a second one naming the periods ("w 1. roku"), then a row
    per Series. The rates of the periods stand from "Oprocentowanie" up to "Odsetki (zł)", the interest from there up
    to "Marża" (or the end)."""
    rows = [sheet.row_values(index) for index in range(sheet.nrows)]
    header_at = next((i for i, row in enumerate(rows) if "Seria" in _texts(row)), None)
    if header_at is None:
        raise BondDataError(f"W zakładce {sheet.name} pliku MF brak nagłówka „Seria”.")
    header = _texts(rows[header_at])
    columns = {name: header.index(name) for name in header if name}
    try:
        series_at, isin_at = columns["Seria"], columns["Kod ISIN"]
        start_at, end_at = columns["Początek sprzedaży"], columns["Koniec sprzedaży"]
        issue_at, rollover_at = columns["Cena emisyjna"], columns["Cena zamiany"]
        rates_at, interest_at = columns["Oprocentowanie"], columns["Odsetki (zł)"]
    except KeyError as missing:
        raise BondDataError(f"W zakładce {sheet.name} pliku MF brak kolumny {missing}.") from None
    margin_at = columns.get("Marża")
    periods_named = header_at + 1 < len(rows) and not _text(rows[header_at + 1][series_at])
    if periods_named:
        rate_columns = range(rates_at, interest_at)
        interest_columns = range(interest_at, margin_at if margin_at is not None else len(header))
    else:
        rate_columns, interest_columns = range(rates_at, rates_at + 1), range(interest_at, interest_at + 1)
    series = []
    for row in rows[header_at + 1 :]:
        name = _text(row[series_at])
        if not SERIES.fullmatch(name):
            continue
        try:
            series.append(
                SeriesTerms(
                    series=name,
                    isin=_text(row[isin_at]),
                    sale_start=_date(row[start_at], datemode),
                    sale_end=_date(row[end_at], datemode),
                    issue_price=_required(row[issue_at]),
                    rollover_price=_number(row[rollover_at]),
                    margin=None if margin_at is None else _number(row[margin_at]),
                    rates=tuple(_number(row[i]) for i in rate_columns),
                    interest=tuple(_number(row[i]) for i in interest_columns),
                )
            )
        except ValueError, TypeError, OverflowError, XLRDError:
            raise BondDataError(f"Nieprawidłowy wiersz serii {name} w pliku MF.") from None
    if not series:
        raise BondDataError(f"W zakładce {sheet.name} pliku MF brak serii.")
    return series


def _texts(row: Sequence[object]) -> list[str]:
    return [_text(cell) for cell in row]


def _text(cell: object) -> str:
    return cell.strip() if isinstance(cell, str) else ""


def _number(cell: object) -> Decimal | None:
    """A number cell as a Decimal without the float's noise (0.07200000000000001 is 0.072); text such as "-" or an
    empty cell is None."""
    if isinstance(cell, bool) or not isinstance(cell, int | float):
        return None
    text = f"{round(cell, 6):.6f}".rstrip("0").rstrip(".")
    return Decimal(text)


def _required(cell: object) -> Decimal:
    number = _number(cell)
    if number is None:
        raise ValueError(cell)
    return number


def _date(cell: object, datemode: Literal[0, 1]) -> date:
    if not isinstance(cell, float):
        raise ValueError(cell)
    return xlrd.xldate.xldate_as_datetime(cell, datemode).date()


def parse_gus_csv(content: bytes) -> list[CpiReading]:
    """The months with a year-on-year or a month-on-month index from the GUS CSV (``;``, decimal comma, in cp1250
    unless it starts with a UTF-8 byte order mark), oldest first."""
    text = content.decode("utf-8-sig") if content.startswith(b"\xef\xbb\xbf") else content.decode("cp1250")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    if not rows:
        raise BondDataError("Plik CSV GUS ze wskaźnikami cen jest pusty.")
    header = [name.strip() for name in rows[0]]
    try:
        kind_at, year_at, month_at = header.index("Sposób prezentacji"), header.index("Rok"), header.index("Miesiąc")
        value_at = header.index("Wartość")
    except ValueError:
        raise BondDataError("Plik CSV GUS ze wskaźnikami cen ma nieznany układ kolumn.") from None
    indices: dict[tuple[int, int], dict[str, Decimal]] = {}
    for row in rows[1:]:
        if len(row) <= value_at or row[kind_at] not in (YEAR_ON_YEAR, MONTH_ON_MONTH) or not row[value_at].strip():
            continue
        try:
            month = (int(row[year_at]), int(row[month_at]))
            indices.setdefault(month, {})[row[kind_at]] = Decimal(row[value_at].strip().replace(",", "."))
        except ValueError, InvalidOperation:
            raise BondDataError(f"Nieprawidłowy wiersz w pliku CSV GUS: {';'.join(row)}") from None
    if not indices:
        raise BondDataError("W pliku CSV GUS brak wskaźników cen.")
    return [
        CpiReading(year, month, values.get(YEAR_ON_YEAR), values.get(MONTH_ON_MONTH))
        for (year, month), values in sorted(indices.items())
    ]


def parse_nbp_rates(content: bytes) -> list[ReferenceRate]:
    """The reference rate ("ref") of every entry of the NBP archive, oldest first, as a fraction (3,75 is 0.0375)."""
    try:
        root = ElementTree.fromstring(content)
        rates = []
        for entry in root.iter("pozycje"):
            for rate in entry.iter("pozycja"):
                if rate.get("id") == "ref":
                    percent = Decimal((rate.get("oprocentowanie") or "").replace(",", "."))
                    valid_from = date.fromisoformat(entry.get("obowiazuje_od") or "")
                    rates.append(ReferenceRate(valid_from, percent / 100))
    except ElementTree.ParseError, ValueError, InvalidOperation:
        raise BondDataError("Nieprawidłowy plik stóp procentowych NBP.") from None
    if not rates:
        raise BondDataError("W pliku stóp procentowych NBP brak stopy referencyjnej.")
    return sorted(rates, key=lambda rate: rate.valid_from)


@dataclass(frozen=True)
class BondDataSources:
    """Where ``refresh_bond_data`` takes each kind of data from; injectable so tests run on saved files."""

    series: Callable[[], list[SeriesTerms]]
    cpi: Callable[[], list[CpiReading]]
    reference_rates: Callable[[], list[ReferenceRate]]

    @classmethod
    def real(cls) -> BondDataSources:
        return cls(MfBondFile().series, GusCpi().readings, NbpReferenceRates().rates)


def bond_data_due(statuses: dict[str, BondDataStatus], now: datetime) -> bool:
    """Some source has not been fetched successfully today."""
    return any(_due(statuses.get(key), now) for key in BOND_DATA_NAMES)


def _due(status: BondDataStatus | None, now: datetime) -> bool:
    return status is None or status.succeeded_at is None or status.succeeded_at.date() < now.date()


def refresh_bond_data(
    engine: Engine, sources: BondDataSources, now: Callable[[], datetime] = datetime.now
) -> dict[str, str]:
    """Fetch each source not fetched successfully today and replace its saved copy; returns the failures (Polish
    reasons by source key). A failing source keeps its last copy and never stops the others."""
    statuses = bond_data_statuses(engine)
    steps: dict[str, Callable[[], None]] = {
        MF: lambda: save_series_terms(engine, sources.series()),
        GUS: lambda: save_cpi(engine, sources.cpi()),
        NBP_REFERENCE: lambda: save_reference_rates(engine, sources.reference_rates()),
    }
    failures = {}
    for key, step in steps.items():
        if not _due(statuses.get(key), now()):
            continue
        try:
            step()
        except BondDataError as error:
            failures[key] = str(error)
        except Exception as error:  # noqa: BLE001 - a broken source must not stop the others
            failures[key] = f"Nieoczekiwany błąd źródła: {error}"
        mark_bond_data(engine, key, now(), failures.get(key))
    return failures
