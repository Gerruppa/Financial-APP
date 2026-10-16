"""The Wyniki tab (issue #74, spec section 5 and 6.1): the View Scope's results over the period and over the fixed
periods YTD, 1R, 3L and Od początku, all from History, so they wait until it is computed.

Unlike the Dashboard's XIRR, which ends at today's value with Manual Prices, these end at History's value (spec 6.1).
The real return is the TWR after the GUS CPI's inflation over the period (L-10), from the saved bond data.
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_count, format_date, format_month, format_percent
from financial_app.domain.inflation import Inflation
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.results import TABLE_PRESETS, PeriodResults, ResultsRow, period_results, results_rows
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.bond_data import load_cpi
from financial_app.ui.charts import drawdown_chart
from financial_app.ui.info import card_title
from financial_app.ui.periods import PeriodChoice, period_selector
from financial_app.ui.view_scope import ViewScope

DASH = "—"
NO_CPI = "brak CPI GUS za ten okres"
# Behind the "i" of the tiles that need explaining, by their key
TILE_INFO = {
    "xirr": (
        "Twoja roczna stopa zwrotu z uwzględnieniem terminów i kwot wpłat i wypłat, jak oprocentowanie lokaty, "
        "która dałaby ten sam wynik. Pokazuje, jak urosły Twoje pieniądze, łącznie z tym, kiedy je dokładałeś.\n\n"
        "Przy okresie krótszym niż rok jest przeliczona na rok, więc potrafi być przesadnie wysoka lub niska."
    ),
    "twr": (
        "Stopa zwrotu za cały wybrany okres (nie rocznie), liczona tak, jakby nie było żadnych wpłat ani wypłat: "
        "mierzy samą skuteczność inwestycji, niezależnie od tego, kiedy i ile wpłacałeś.\n\n"
        "Nadaje się do porównania z benchmarkiem lub innym kontem. Gdy XIRR jest wyższy od TWR (w przeliczeniu na "
        "rok), wpłaty trafiały w dobre momenty; gdy niższy, w gorsze."
    ),
}


@dataclass
class ResultsPage:
    """The Wyniki tab of the View Scope, under the period selector; ``history`` gives History's days once computed."""

    engine: Engine
    scope: ViewScope
    period: PeriodChoice
    history: Callable[[], list[DayValue] | None]

    def refresh(self) -> None:
        """Redraw the results if they are on screen (e.g. once History is computed)."""
        self.content.refresh()

    def __post_init__(self) -> None:
        self.period.on_change(self.refresh)

    def build(self) -> None:
        ui.label("Wyniki").classes("text-2xl font-bold")
        period_selector(self.period)
        with ui.column().classes("w-full max-w-6xl").mark("results"):
            self.content()

    @ui.refreshable_method
    def content(self) -> None:
        days = self.history()
        if days is None:
            ui.label("Wyniki: wyliczanie historii…").classes("text-gray-500").mark("results-pending")
            return
        if not days:
            ui.label("Wyniki pojawią się po pierwszej transakcji.").classes("text-gray-500").mark("results-empty")
            return
        first, last = self.period.dates()
        account_id = self.scope.account_id
        _tiles(period_results(days, first, last, account_id, load_cpi(self.engine)))
        drawdown_chart(days, first, last, account_id, "results-drawdown")
        _table(results_rows(days, list_accounts(self.engine), account_id, self.period.today()))


def _percent(fraction: Decimal | None) -> str:
    return DASH if fraction is None else format_percent(fraction * 100)


def _tiles(results: PeriodResults) -> None:
    drawdown = results.max_drawdown
    if drawdown is None:
        depth, fall, recovery = format_percent(0), "", DASH
    else:
        depth = _percent(drawdown.depth)
        fall = f"{format_date(drawdown.peak)} – {format_date(drawdown.trough)}"
        days = results.recovery_days
        recovery = "nie odrobione" if days is None else format_count(days, "dzień", "dni", "dni")
    tiles = (
        ("xirr", "XIRR (rocznie)", _percent(results.xirr), ""),
        ("twr", "TWR (za okres)", _percent(results.twr), ""),
        ("max-drawdown", "Maks. obsunięcie (TWR)", depth, fall),
        ("recovery", "Czas odrabiania", recovery, "od dołka do szczytu" if drawdown else ""),
        ("volatility", "Zmienność (rocznie)", _percent(results.volatility), "dzienne zwroty TWR, dni robocze"),
        ("real", "Wynik realny (TWR po inflacji)", _percent(results.real_return), _inflation_note(results.inflation)),
    )
    with (
        ui.element("div")
        .classes("grid w-full gap-4")
        .style("grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr))")
    ):
        for key, title, text, note in tiles:
            with ui.card().classes("gap-1"):
                card_title(title, TILE_INFO.get(key), f"results-{key}", "text-sm text-gray-500")
                ui.label(text).classes("text-xl font-medium").mark(f"results-{key}")
                if note:
                    ui.label(note).classes("text-xs text-gray-500")


def _inflation_note(inflation: Inflation | None) -> str:
    """The period's inflation, and the month GUS has published up to when the period runs past it."""
    if inflation is None:
        return NO_CPI
    note = f"inflacja (CPI) {_percent(inflation.rate)}"
    return note if inflation.complete else f"{note} · CPI do {format_month(inflation.known_until)}"


TABLE_COLUMNS = f"grid-template-columns: minmax(8rem, 2fr) repeat({2 * len(TABLE_PRESETS)}, minmax(5rem, 1fr))"


def _table(rows: list[ResultsRow]) -> None:
    """XIRR and TWR over each fixed period, a row for the Total and each Account (or the scope's Account)."""
    with ui.card().classes("w-full overflow-x-auto").mark("results-table"):
        ui.label("Okresy").classes("text-lg font-medium")
        with ui.element("div").classes("grid w-full gap-x-4 text-sm font-medium").style(TABLE_COLUMNS):
            ui.label("")
            for preset in TABLE_PRESETS:
                ui.label(preset.label).classes("text-center").style("grid-column: span 2")
            ui.label("Konto")
            for _ in TABLE_PRESETS:
                ui.label("XIRR").classes("text-right")
                ui.label("TWR").classes("text-right")
        for row in rows:
            line = ui.element("div").classes("grid w-full gap-x-4 border-t py-1 text-sm").style(TABLE_COLUMNS)
            with line.mark("results-row"):
                ui.label("Total" if row.account is None else row.account.name).classes("font-medium")
                for preset in TABLE_PRESETS:
                    returns = row.returns[preset]
                    ui.label(_percent(returns.xirr)).classes("text-right")
                    ui.label(_percent(returns.twr)).classes("text-right")
