"""The Benchmarki tab (issue #91, spec 5 and 6): the View Scope's Portfolio against CPI, catalog Instruments and other
Accounts over the period, as the sheet's Benchmarki tab compares them: a table of today's values with the Portfolio's
difference, which ones the chart shows, and the values over time. Benchmarks are added and removed here; the sheet's
defaults come in on the first visit, their Instruments' history fetched with History's."""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.benchmarks import Benchmark, BenchmarkError, BenchmarkKind, ComparisonRow, parse_offset
from financial_app.domain.formatting import format_percent, format_pln
from financial_app.domain.portfolio_history import DayValue
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.benchmarks import add_benchmark, delete_benchmark, ensure_default_benchmarks, set_shown
from financial_app.persistence.instruments import list_instruments
from financial_app.sources.benchmarks import benchmark_comparison
from financial_app.ui.charts import pln_bars_chart, pln_lines_chart
from financial_app.ui.periods import PeriodChoice, period_selector
from financial_app.ui.view_scope import ViewScope

DASH = "—"
SHORT_HISTORY = "* Benchmark nie ma notowań z całego okresu: do pierwszego z nich wpłaty czekają w gotówce."
COLUMNS = "grid-template-columns: minmax(10rem, 2fr) repeat(4, minmax(6rem, 1fr)) 6rem 3rem"
HEADERS = (
    "Nazwa",
    "Wartość obecna",
    "Portfel vs benchmark",
    "Portfel vs benchmark %",
    "Zwrot (TWR)",
    "Na wykresie",
    "",
)
KINDS = {BenchmarkKind.CPI: "CPI (inflacja)", BenchmarkKind.INSTRUMENT: "Instrument", BenchmarkKind.ACCOUNT: "Konto"}


@dataclass
class BenchmarksPage:
    """The Benchmarki tab of the View Scope; ``history`` gives History's days once computed, ``fetch`` starts fetching
    the missing history (after a benchmark Instrument was added)."""

    engine: Engine
    scope: ViewScope
    period: PeriodChoice
    history: Callable[[], list[DayValue] | None]
    fetch: Callable[[], None]

    def __post_init__(self) -> None:
        self.period.on_change(self.refresh)

    def refresh(self) -> None:
        """Redraw the comparison if it is on screen (e.g. once History is computed)."""
        self.content.refresh()

    def build(self) -> None:
        ui.label("Benchmarki").classes("text-2xl font-bold")
        ui.label(
            "Każda wpłata i wypłata trafia do benchmarku w dniu operacji po jego cenie w PLN, bez opłat i podatków."
        ).classes("text-sm text-gray-600")
        if ensure_default_benchmarks(self.engine):
            self.fetch()
        period_selector(self.period)
        with ui.column().classes("w-full max-w-6xl").mark("benchmarks"):
            self.content()
            self._add_form()

    @ui.refreshable_method
    def content(self) -> None:
        days = self.history()
        if days is None:
            ui.label("Benchmarki: wyliczanie historii…").classes("text-gray-500").mark("benchmarks-pending")
            return
        if not days:
            ui.label("Benchmarki pojawią się po pierwszej transakcji.").classes("text-gray-500").mark(
                "benchmarks-empty"
            )
            return
        first, last = self.period.dates()
        rows = benchmark_comparison(self.engine, days, first, last, self.scope.account_id)
        self._table(rows)
        shown = [row for row in rows if row.benchmark is None or row.benchmark.shown]
        pln_bars_chart(
            "Wartość obecna",
            "benchmarks-values",
            [row.name for row in shown],
            {"Wartość": [row.value for row in shown]},
        )
        pln_lines_chart(
            "Portfel vs CPI i benchmarki",
            "benchmarks-history",
            [day for day, _ in rows[0].series],
            {row.name: [value for _, value in row.series] for row in shown},
        )

    def _table(self, rows: list[ComparisonRow]) -> None:
        with ui.card().classes("w-full overflow-x-auto").mark("benchmarks-table"):
            with ui.element("div").classes("grid w-full gap-x-4 text-sm font-medium").style(COLUMNS):
                for header in HEADERS:
                    ui.label(header)
            for row in rows:
                line = ui.element("div").classes("grid w-full items-center gap-x-4 border-t py-1 text-sm")
                with line.style(COLUMNS).mark("benchmark-row"):
                    name = ui.label(f"{row.name}*" if row.short_history else row.name).classes("font-medium")
                    if row.short_history:
                        name.classes("text-red-700")
                    ui.label(format_pln(row.value)).classes("text-right")
                    ui.label(DASH if row.difference is None else format_pln(row.difference, signed=True)).classes(
                        "text-right"
                    )
                    ui.label(_percent(row.difference_rate, signed=True)).classes("text-right")
                    ui.label(_percent(row.twr)).classes("text-right")
                    self._row_controls(row.benchmark)
            if any(row.short_history for row in rows):
                ui.label(SHORT_HISTORY).classes("text-xs text-red-700")

    def _row_controls(self, benchmark: Benchmark | None) -> None:
        if benchmark is None or benchmark.id is None:
            ui.checkbox(value=True).props("disable")
            ui.label("")
            return
        benchmark_id = benchmark.id

        def toggle(shown: bool) -> None:
            set_shown(self.engine, benchmark_id, shown)
            self.refresh()

        ui.checkbox(value=benchmark.shown, on_change=lambda e: toggle(bool(e.value))).mark(
            f"benchmark-shown-{benchmark_id}"
        )

        def remove() -> None:
            delete_benchmark(self.engine, benchmark_id)
            self.refresh()

        ui.button(icon="delete", on_click=remove).props(
            'flat round dense color=grey-7 aria-label="Usuń benchmark"'
        ).mark(f"benchmark-delete-{benchmark_id}")

    def _add_form(self) -> None:
        instruments = {i.id: i.name for i in list_instruments(self.engine)}
        accounts = {a.id: a.name for a in list_accounts(self.engine)}
        with ui.card().classes("w-full").mark("benchmark-add"):
            ui.label("Dodaj benchmark").classes("text-lg font-medium")
            with ui.row().classes("w-full items-end gap-4"):
                kind = ui.select(
                    {k.value: label for k, label in KINDS.items()}, value=BenchmarkKind.INSTRUMENT.value, label="Rodzaj"
                ).classes("w-40")
                kind.mark("benchmark-kind")
                instrument = ui.select(instruments, label="Instrument", with_input=True).classes("w-64")
                instrument.mark("benchmark-instrument")
                account = ui.select(accounts, label="Konto").classes("w-48").mark("benchmark-account")
                offset = ui.input("Dodatek (pp/rok)", placeholder="np. 3").classes("w-36").mark("benchmark-offset")

                def kind_chosen() -> None:
                    instrument.set_visibility(kind.value == BenchmarkKind.INSTRUMENT.value)
                    account.set_visibility(kind.value == BenchmarkKind.ACCOUNT.value)

                kind.on_value_change(kind_chosen)
                kind_chosen()

                def add() -> None:
                    chosen = BenchmarkKind(kind.value)
                    try:
                        benchmark = Benchmark(
                            chosen,
                            instrument.value if chosen is BenchmarkKind.INSTRUMENT else None,
                            account.value if chosen is BenchmarkKind.ACCOUNT else None,
                            parse_offset(offset.value or ""),
                        )
                        add_benchmark(self.engine, benchmark)
                    except BenchmarkError as error:
                        ui.notify(str(error), type="warning")
                        return
                    offset.value = ""
                    self.refresh()
                    if chosen is BenchmarkKind.INSTRUMENT:
                        self.fetch()

                ui.button("Dodaj", on_click=add).props("unelevated color=indigo").mark("benchmark-add-button")


def _percent(fraction: Decimal | None, signed: bool = False) -> str:
    return DASH if fraction is None else format_percent(fraction * 100, signed=signed)
