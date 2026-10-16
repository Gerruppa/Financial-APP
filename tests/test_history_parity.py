"""Parity of History with the Historia tab of the user's Inwestomat copy (spec 6.1, 9; ADR-0002, ADR-0006; issue #70).

The sheet's Transakcje rows are imported as they are, each Instrument gets the Yahoo symbol of its sheet ticker, and
History is computed from Yahoo's daily closes and the NBP Rates, the Bond Series from the MF file saved in the test
fixtures. At the last Historia row of each month the total value, the Net Deposits and the value of each Asset Class are
compared with the sheet's. The sheet wrote each row from the prices of that moment, so a difference counts only when it
is over 1% of the sheet's figure and over 50 PLN. The tab has no Multi-asset column, so Multi-asset is compared only
within the total.

The workbook is personal data: it stays in ``reference/`` (git-ignored), is read at test time, and the tests are skipped
when it is missing. The fetched prices and rates are cached in ``CACHE`` next to it, so only the first run needs the
network; the cache is rebuilt when the sheet's Transakcje or the Yahoo symbols change. Nothing from the workbook is
copied here. A difference is accepted only when a ``Deviation`` covers its measure and day; each is also recorded in
spec section 6.1 or 9.
"""

import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.history import ONE_DAY
from financial_app.domain.portfolio_history import CASH_CLASS, FOREIGN_CASH_CLASS, DayValue, daily_history
from financial_app.domain.prices import YAHOO
from financial_app.domain.spreadsheet_import import SheetLine, fingerprints
from financial_app.domain.transactions import PLN
from financial_app.persistence.accounts import add_account
from financial_app.persistence.bond_data import save_series_terms
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import list_instruments, update_instrument
from financial_app.persistence.transactions import list_transactions
from financial_app.sources.bond_data import parse_mf_file
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates
from financial_app.sources.portfolio_history import PortfolioHistory
from financial_app.sources.spreadsheet import Decisions, read_sheet_lines, save_import

REFERENCE = Path(__file__).resolve().parents[1] / "reference" / "Newest portfolio.xlsx"
CACHE = REFERENCE.with_name("historia-parity.sqlite3")
MF_FILE = Path(__file__).parent / "fixtures" / "mf" / "dane_obligacji_detalicznych.xls"
RELATIVE_TOLERANCE = Decimal("0.01")
ABSOLUTE_TOLERANCE = Decimal(50)
TOTAL = "Wartość konta"
NET_DEPOSITS = "Wpłaty netto"
# The Historia columns compared besides TOTAL and NET_DEPOSITS: one per Asset Class, PLN cash and foreign cash
CLASSES = (
    CASH_CLASS,
    "Akcje polskie",
    "Akcje zagraniczne",
    "Obligacje skarbowe polskie",
    "Obligacje skarbowe zagraniczne",
    "Obligacje korporacyjne polskie",
    "Obligacje korporacyjne zagraniczne",
    "Metale i surowce",
    "Kryptowaluty",
    "Inne",
    FOREIGN_CASH_CLASS,
)
# Yahoo's suffix for the exchange of a sheet ticker (Google Finance's EXCH:SYM)
YAHOO_SUFFIXES = {"WSE": ".WA", "LON": ".L", "FRA": ".DE", "ETR": ".DE", "AMS": ".AS", "EPA": ".PA", "BIT": ".MI"}


@dataclass(frozen=True)
class Difference:
    day: date
    measure: str
    sheet: Decimal
    app: Decimal

    def __str__(self) -> str:
        return f"{self.day} {self.measure}: arkusz {self.sheet:.2f}, aplikacja {self.app:.2f}"


@dataclass(frozen=True)
class Deviation:
    """A known difference (spec 6.1, 9): the measures it may cover, on ``days`` (``None``: every month end)."""

    measures: frozenset[str]
    reason: str
    days: frozenset[date] | None = None

    def covers(self, difference: Difference) -> bool:
        return difference.measure in self.measures and (self.days is None or difference.day in self.days)


FROZEN_ROWS = (
    "Arkusz zapisuje wiersz Historii raz, z bieżącego stanu, więc Transakcja wpisana później z wcześniejszą datą nie "
    "trafia do wierszy już zapisanych; aplikacja przelicza Historię (ADR-0002, spec 9)."
)


def deviations(historia: dict[date, dict[str, Decimal]], history: dict[date, DayValue]) -> tuple[Deviation, ...]:
    return (Deviation(frozenset({*CLASSES, TOTAL, NET_DEPOSITS}), FROZEN_ROWS, late_entry_days(historia, history)),)


def late_entry_days(historia: dict[date, dict[str, Decimal]], history: dict[date, DayValue]) -> frozenset[date]:
    """The month ends whose Net Deposits the sheet caught up with only later: they differ from the app's, and on the
    next Historia day the sheet's Net Deposits change they agree with the app's again, so the Deposits or Withdrawals
    were there, only entered after the row was written."""
    days = sorted(historia)
    found = set()
    for day in month_ends(historia):
        sheet = historia[day][NET_DEPOSITS]
        if within_tolerance(sheet, history[day].net_deposits):
            continue
        later = next((d for d in days if d > day and historia[d][NET_DEPOSITS] != sheet), None)
        if later is not None and within_tolerance(historia[later][NET_DEPOSITS], history[later].net_deposits):
            found.add(day)
    return frozenset(found)


def within_tolerance(sheet: Decimal, app: Decimal) -> bool:
    return abs(sheet - app) <= max(abs(sheet) * RELATIVE_TOLERANCE, ABSOLUTE_TOLERANCE)


def yahoo_symbol(ticker: str) -> str | None:
    """The Yahoo symbol of a sheet ticker: a listing gets its exchange's suffix, a Google Finance continuous future
    (``COMEX:GCW00``) Yahoo's front-month one (``GC=F``)."""
    exchange, _, symbol = ticker.strip().upper().partition(":")
    if not symbol:
        return None
    if future := re.fullmatch(r"(\w+)W00", symbol):
        return f"{future[1]}=F"
    suffix = YAHOO_SUFFIXES.get(exchange)
    return None if suffix is None else symbol + suffix


def read_historia(path: Path) -> dict[date, dict[str, Decimal]]:
    """The Historia tab's rows by day, read by the names of its columns."""
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = workbook["Historia"].iter_rows(values_only=True)
        header = [str(cell or "").strip() for cell in next(rows)]
        column = {name: index for index, name in enumerate(header) if name}
        days: dict[date, dict[str, Decimal]] = {}
        for row in rows:
            day = row[column["Data"]]
            if not isinstance(day, datetime):
                continue
            days[day.date()] = {name: Decimal(str(row[column[name]] or 0)) for name in (*CLASSES, TOTAL, NET_DEPOSITS)}
        return days
    finally:
        workbook.close()


def month_ends(days: dict[date, dict[str, Decimal]]) -> list[date]:
    """The last Historia day of each month."""
    last: dict[tuple[int, int], date] = {}
    for day in days:
        last[(day.year, day.month)] = max(day, last.get((day.year, day.month), day))
    return sorted(last.values())


def _yahoo_symbols(lines: list[SheetLine]) -> dict[str, str]:
    """The Yahoo symbol by Instrument name (upper case), from the sheet tickers."""
    return {
        line.ticker.strip().partition(":")[2].upper(): symbol for line in lines if (symbol := yahoo_symbol(line.ticker))
    }


def _cache_is_current(engine: Engine, lines: list[SheetLine]) -> bool:
    """Whether the cache holds exactly the sheet's Transakcje and the Yahoo symbols they give."""
    saved = {t.external_id for t in list_transactions(engine)}
    symbols = {i.name.upper(): i.source_symbols[YAHOO] for i in list_instruments(engine) if YAHOO in i.source_symbols}
    return saved == set(fingerprints(lines)) and symbols == _yahoo_symbols(lines)


def _import(engine: Engine, lines: list[SheetLine], rates: NbpRates) -> None:
    """The sheet's Transakcje saved with the sheet's Accounts, and each Instrument's Yahoo symbol from its ticker."""
    currencies: dict[str, set[str]] = {}
    for line in lines:
        currencies.setdefault(line.account, {PLN}).add(line.currency)
    for account, codes in currencies.items():
        wrapper = {"IKE": AccountType.IKE, "IKZE": AccountType.IKZE}.get(account, AccountType.REGULAR)
        add_account(engine, AccountDraft(account, "Arkusz", wrapper, tuple(sorted(codes))))
    save_import(engine, lines, rates, Decisions())
    symbols = _yahoo_symbols(lines)
    for instrument in list_instruments(engine):
        if instrument.name.upper() in symbols:
            draft = replace(instrument, source_symbols={YAHOO: symbols[instrument.name.upper()]})
            update_instrument(engine, instrument.id, draft)


@pytest.fixture(scope="module")
def historia() -> dict[date, dict[str, Decimal]]:
    if not REFERENCE.exists():
        pytest.skip("Brak arkusza referencyjnego w reference/ – test porównawczy pominięty.")
    return read_historia(REFERENCE)


@pytest.fixture(scope="module")
def history(historia: dict[date, dict[str, Decimal]]) -> dict[date, DayValue]:
    """History up to the last Historia day, from the cached prices and rates (fetched when missing)."""
    lines = read_sheet_lines(REFERENCE)
    engine = init_db(CACHE)
    if not _cache_is_current(engine, lines):
        engine.dispose()
        CACHE.unlink()
        engine = init_db(CACHE)
        _import(engine, lines, NbpRates(engine))
    save_series_terms(engine, parse_mf_file(MF_FILE.read_bytes()))
    last = max(historia)
    service = PortfolioHistory(engine, QuoteHistory(engine), NbpRates(engine), today=lambda: last + ONE_DAY)
    failed = service.fetch()
    assert not failed.instruments and not failed.currencies, f"Nie pobrano historii: {failed}"
    inputs = service.inputs()
    assert inputs is not None
    values = daily_history(
        inputs.transactions, inputs.instruments, inputs.prices, inputs.rates, inputs.first, inputs.last, inputs.bonds
    )
    engine.dispose()
    return {value.day: value for value in values}


def _measures(value: DayValue) -> dict[str, Decimal]:
    return {name: value.classes.get(name, Decimal(0)) for name in CLASSES} | {
        TOTAL: value.total,
        NET_DEPOSITS: value.net_deposits,
    }


def compare(historia: dict[date, dict[str, Decimal]], history: dict[date, DayValue]) -> list[Difference]:
    """Every measure at a month end that differs from the sheet's by more than 1% and more than 50 PLN."""
    differences = []
    for day in month_ends(historia):
        app = _measures(history[day])
        for measure, sheet in historia[day].items():
            if not within_tolerance(sheet, app[measure]):
                differences.append(Difference(day, measure, sheet, app[measure].quantize(Decimal("0.01"))))
    return differences


def test_yahoo_symbol_follows_the_exchange_of_the_sheet_ticker() -> None:
    assert yahoo_symbol("WSE:ETFPZUWORLD") == "ETFPZUWORLD.WA"
    assert yahoo_symbol("LON:VUAA") == "VUAA.L"
    assert yahoo_symbol("FRA:SXR8") == "SXR8.DE"
    assert yahoo_symbol("COMEX:GCW00") == "GC=F"
    assert yahoo_symbol("EDO-220536") is None
    assert yahoo_symbol("NYSE:XYZ") is None


def test_month_ends_are_the_last_historia_day_of_each_month() -> None:
    days: dict[date, dict[str, Decimal]] = {
        day: {} for day in (date(2026, 5, 5), date(2026, 5, 31), date(2026, 6, 29), date(2026, 7, 1))
    }
    assert month_ends(days) == [date(2026, 5, 31), date(2026, 6, 29), date(2026, 7, 1)]


def test_history_matches_the_historia_tab_at_each_month_end(
    historia: dict[date, dict[str, Decimal]], history: dict[date, DayValue]
) -> None:
    known = deviations(historia, history)
    found = [str(d) for d in compare(historia, history) if not any(dev.covers(d) for dev in known)]
    assert not found, "\n".join(found)


def test_every_known_deviation_still_occurs(
    historia: dict[date, dict[str, Decimal]], history: dict[date, DayValue]
) -> None:
    """A deviation that no longer differs is stale and must be removed from ``deviations``."""
    differences = compare(historia, history)
    stale = [dev.reason for dev in deviations(historia, history) if not any(dev.covers(d) for d in differences)]
    assert not stale, f"Usuń nieaktualne odstępstwa: {stale}"
