"""The Podsumowanie sprzedaży tab (issue #92, spec 5 and 10): the View Scope's Sale Pairs sold within the period, newest
sale first, with the statistics of those closed positions above them, as the sheet's Sprzedaż Podsumowanie tab lists
them from the single FIFO engine."""

from dataclasses import dataclass
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.formatting import (
    format_count,
    format_date,
    format_number,
    format_percent,
    format_pln,
    format_quantity,
)
from financial_app.domain.sale_summary import SalePair, SaleStats, in_view, sale_pairs, sale_stats
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import transactions_in_entry_order
from financial_app.ui.changes import Change
from financial_app.ui.periods import PeriodChoice, period_selector
from financial_app.ui.view_scope import ViewScope

DASH = "—"
COLUMNS = "grid-template-columns: minmax(10rem, 2.5fr) minmax(8rem, 1.5fr) repeat(11, minmax(5.5rem, 1fr))"
HEADERS = (
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
NUMBER_FROM = HEADERS.index("Liczba")  # the columns from Liczba on hold numbers


@dataclass
class SaleSummaryPage:
    """The Podsumowanie sprzedaży tab of the View Scope over the period."""

    # The changes it redraws on (ui/changes.py)
    CHANGES = frozenset({Change.TRANSACTIONS, Change.SCOPE})

    engine: Engine
    scope: ViewScope
    period: PeriodChoice

    def __post_init__(self) -> None:
        self.period.on_change(self.refresh)

    def refresh(self) -> None:
        """Redraw the tab if it is on screen (e.g. after a save or a scope change)."""
        self.content.refresh()

    def build(self) -> None:
        ui.label("Podsumowanie sprzedaży").classes("text-2xl font-bold")
        period_selector(self.period)
        with ui.column().classes("w-full").mark("sale-summary"):
            self.content()

    @ui.refreshable_method
    def content(self) -> None:
        first, last = self.period.dates()
        pairs = in_view(sale_pairs(transactions_in_entry_order(self.engine)), self.scope.account_id, first, last)
        stats = sale_stats(pairs)
        if stats is None:
            ui.label("Brak sprzedaży w tym okresie.").classes("text-gray-500").mark("sale-empty")
            return
        names = {i.id: i.name for i in list_instruments(self.engine)}
        accounts = {a.id: a.name for a in list_accounts(self.engine)}
        _tiles(stats, names)
        _table(pairs, names, accounts)


def _tiles(stats: SaleStats, names: dict[int, str]) -> None:
    def pair_note(pair: SalePair) -> str:
        return f"{names.get(pair.instrument_id, '')} · {format_date(pair.sold_on)}"

    tiles = (
        ("count", "Zamknięte pary", format_count(stats.count, "para", "pary", "par"), ""),
        ("win-rate", "Zyskowne", format_percent(stats.win_rate * 100), "odsetek par z zyskiem"),
        ("days", "Średni czas trzymania", f"{format_number(stats.average_days, 0)} dni", ""),
        ("result", "Wynik", format_pln(stats.result, signed=True), _percent(stats.return_rate)),
        (
            "result-dividends",
            "Wynik z dywidendami",
            format_pln(stats.result_with_dividends, signed=True),
            f"dywidendy {format_pln(stats.dividends)}",
        ),
        ("best", "Najlepsza", format_pln(stats.best.result, signed=True), pair_note(stats.best)),
        ("worst", "Najgorsza", format_pln(stats.worst.result, signed=True), pair_note(stats.worst)),
    )
    with (
        ui.element("div")
        .classes("grid w-full gap-4")
        .style("grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr))")
    ):
        for key, title, text, note in tiles:
            with ui.card().classes("gap-1"):
                ui.label(title).classes("text-sm text-gray-500")
                ui.label(text).classes("text-xl font-medium").mark(f"sale-{key}")
                if note:
                    ui.label(note).classes("text-xs text-gray-500")


def _table(pairs: list[SalePair], names: dict[int, str], accounts: dict[int, str]) -> None:
    # Names wrap in their own column; dates and numbers keep one line, numbers (and their headers) to the right.
    with ui.card().classes("w-full overflow-x-auto").mark("sale-table"):
        with ui.element("div").classes("grid w-full gap-x-3 text-sm font-medium").style(COLUMNS):
            for index, header in enumerate(HEADERS):
                ui.label(header).classes("text-right" if index >= NUMBER_FROM else "").mark("sale-header")
        for pair in pairs:
            with ui.element("div").classes("grid w-full gap-x-3 border-t py-1 text-sm").style(COLUMNS).mark("sale-row"):
                ui.label(names.get(pair.instrument_id, "")).classes("font-medium min-w-0 break-words")
                ui.label(accounts.get(pair.account_id, "")).classes("min-w-0 break-words")
                ui.label(format_date(pair.bought_on)).classes("whitespace-nowrap")
                ui.label(format_date(pair.sold_on)).classes("whitespace-nowrap")
                for text in (
                    format_quantity(pair.quantity),
                    format_pln(pair.cost),
                    format_pln(pair.revenue),
                    format_pln(pair.result, signed=True),
                    _percent(pair.return_rate),
                    str(pair.days_held),
                    format_pln(pair.dividends),
                    format_pln(pair.result_with_dividends, signed=True),
                    _percent(pair.return_with_dividends),
                ):
                    ui.label(text).classes("text-right whitespace-nowrap")


def _percent(fraction: Decimal | None) -> str:
    return DASH if fraction is None else format_percent(fraction * 100, signed=True)
