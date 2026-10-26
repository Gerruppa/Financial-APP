"""The report model (issue #240, parent #239): a report is a title, sections of typed rows and notes, built for a
calendar year and a View Scope from the single FIFO engine (ADR-0003) and the Wyniki calculations, so no figure is
calculated a second time. Renderers (``sources/report_export.py``) turn it into a file; the model knows no file format.

A cell is text, a whole number, a ``Decimal`` amount or quantity, a ``Percent`` (a fraction shown as percent), a date
or ``None`` for an empty cell. Prices and other fetched data come in ready, never fetched here.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account
from financial_app.domain.bonds import CpiReading
from financial_app.domain.formatting import format_month
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.results import PeriodResults, Returns, period_results, results_rows
from financial_app.domain.sale_summary import SalePair, in_view, sale_pairs, sale_stats
from financial_app.domain.transactions import TransactionDraft

ALL_ACCOUNTS = "Wszystkie rachunki"
NOTHING_TO_REPORT = "Brak danych do raportu za ten rok."
NO_CPI = "brak CPI GUS za ten okres"
NOT_RECOVERED = "nie odrobione"


@dataclass(frozen=True)
class Percent:
    """A fraction (0.05 is 5 %) a renderer shows as a percent."""

    fraction: Decimal


Cell = str | int | Decimal | Percent | date | None


@dataclass(frozen=True)
class Section:
    """A table: ``headers`` over ``rows`` of as many cells, with ``notes`` below."""

    title: str
    headers: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Report:
    """What the report is called and its ``sections``; ``name`` is the file name's start. A report with nothing in
    the year has no sections and says so in its ``notes``."""

    name: str
    title: str
    sections: tuple[Section, ...] = ()
    notes: tuple[str, ...] = ()


def last_finished_year(today: date) -> int:
    return today.year - 1


def sale_summary_report(
    transactions: Sequence[TransactionDraft],
    year: int,
    account_id: int | None,
    instrument_names: Mapping[int, str],
    account_names: Mapping[int, str],
) -> Report:
    """The Sale Pairs of ``year`` in the View Scope, newest sale first, with the statistics of those closed positions
    (as the Sell Summary tab shows them)."""
    name = "podsumowanie-sprzedazy"
    title = f"Podsumowanie sprzedaży {year} · {_scope_name(account_id, account_names)}"
    pairs = in_view(sale_pairs(transactions), account_id, date(year, 1, 1), date(year, 12, 31))
    stats = sale_stats(pairs)
    if stats is None:
        return Report(name, title, notes=(NOTHING_TO_REPORT,))
    summary = (
        ("Zamknięte pary", stats.count),
        ("Zyskowne", Percent(stats.win_rate)),
        ("Średni czas trzymania (dni)", stats.average_days),
        ("Koszt", stats.cost),
        ("Przychód", stats.revenue),
        ("Wynik", stats.result),
        ("Rentowność", _percent(stats.return_rate)),
        ("Dywidendy", stats.dividends),
        ("Wynik z dywidendami", stats.result_with_dividends),
        ("Rentowność z dywidendami", _percent(stats.return_with_dividends)),
    )
    return Report(
        name,
        title,
        (
            Section("Podsumowanie", ("Miara", "Wartość"), summary),
            Section("Sprzedaże", _SALE_HEADERS, tuple(_sale_row(p, instrument_names, account_names) for p in pairs)),
        ),
    )


_SALE_HEADERS = (
    "Instrument",
    "Konto",
    "Zakup",
    "Sprzedaż",
    "Liczba",
    "Koszt",
    "Przychód",
    "Wynik",
    "Rentowność",
    "Dni",
    "Dywidendy",
    "Wynik z dyw.",
    "Rentowność z dyw.",
)


def _sale_row(pair: SalePair, instruments: Mapping[int, str], accounts: Mapping[int, str]) -> tuple[Cell, ...]:
    return (
        instruments.get(pair.instrument_id, ""),
        accounts.get(pair.account_id, ""),
        pair.bought_on,
        pair.sold_on,
        pair.quantity,
        pair.cost,
        pair.revenue,
        pair.result,
        _percent(pair.return_rate),
        pair.days_held,
        pair.dividends,
        pair.result_with_dividends,
        _percent(pair.return_with_dividends),
    )


def results_report(
    history: Sequence[DayValue],
    accounts: Sequence[Account],
    account_id: int | None,
    year: int,
    today: date,
    cpi: Iterable[CpiReading],
) -> Report:
    """The View Scope's results over ``year`` (a year in progress up to ``today``) from History, as the Wyniki tab
    gives them over a period, and the same returns of the Total and each Account in the scope."""
    name = "wyniki"
    names = {account.id: account.name for account in accounts}
    title = f"Wyniki {year} · {_scope_name(account_id, names)}"
    first, last = date(year, 1, 1), min(date(year, 12, 31), today)
    if not any(first <= day.day <= last for day in history):
        return Report(name, title, notes=(NOTHING_TO_REPORT,))
    readings = tuple(cpi)
    results = period_results(history, first, last, account_id, readings)
    rows = tuple(
        (
            "Total" if row.account is None else row.account.name,
            *_returns(period_results(history, first, last, None if row.account is None else row.account.id).returns),
        )
        for row in results_rows(history, accounts, account_id, today)
    )
    return Report(
        name,
        title,
        (
            Section("Wyniki roku", ("Miara", "Wartość"), _summary(results), _inflation_notes(results)),
            Section("Konta", ("Konto", "XIRR", "TWR"), rows),
        ),
    )


def _summary(results: PeriodResults) -> tuple[tuple[str, Cell], ...]:
    drawdown = results.max_drawdown
    return (
        ("XIRR (rocznie)", None if results.xirr is None else Percent(results.xirr)),
        ("TWR", Percent(results.twr)),
        ("Maks. obsunięcie (TWR)", Percent(drawdown.depth if drawdown else Decimal(0))),
        ("Obsunięcie od", drawdown.peak if drawdown else None),
        ("Obsunięcie do", drawdown.trough if drawdown else None),
        (
            "Czas odrabiania (dni)",
            NOT_RECOVERED if drawdown and drawdown.recovered_on is None else results.recovery_days,
        ),
        ("Zmienność (rocznie)", _percent(results.volatility)),
        ("Inflacja (CPI)", _percent(results.inflation.rate if results.inflation else None)),
        ("Wynik realny (TWR po inflacji)", _percent(results.real_return)),
    )


def _inflation_notes(results: PeriodResults) -> tuple[str, ...]:
    inflation = results.inflation
    if inflation is None:
        return (NO_CPI,)
    return () if inflation.complete else (f"CPI do {format_month(inflation.known_until)}",)


def _returns(returns: Returns) -> tuple[Cell, Cell]:
    return _percent(returns.xirr), Percent(returns.twr)


def _percent(fraction: Decimal | None) -> Percent | None:
    return None if fraction is None else Percent(fraction)


def _scope_name(account_id: int | None, account_names: Mapping[int, str]) -> str:
    return ALL_ACCOUNTS if account_id is None else account_names[account_id]
