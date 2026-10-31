"""The "Eksportuj XLSX" control of a report tab (issue #240): a year choice, by default the last finished calendar year,
and the button that hands the report's file to the browser, as the Transakcje tab does."""

from collections.abc import Callable
from datetime import date

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.report import last_finished_year
from financial_app.persistence.transactions import list_transactions


def export_controls(
    key: str, engine: Engine, today: date, export: Callable[[int], None], pdf: Callable[[int], None] | None = None
) -> None:
    """A year select (``<key>-export-year``) from the first Transaction's year to this one, and the button
    (``<key>-export``) calling ``export`` with the chosen year; with ``pdf``, a second button (``<key>-pdf``)
    calls it, for the annual PDF report."""
    default = last_finished_year(today)
    first = min((t.date.year for t in list_transactions(engine)), default=default)
    years = list(range(today.year, min(first, default) - 1, -1))
    with ui.row().classes("items-center gap-2"):
        # Named for the export it feeds, so that it is not read as a filter of the tab beside its period
        year = ui.select(years, value=default, label="Rok eksportu").props("dense").classes("w-32")
        year.tooltip("Rok, za który powstanie plik; nie zmienia tego, co widać na stronie").mark(f"{key}-export-year")
        ui.button("Eksportuj XLSX", icon="download", on_click=lambda: export(int(year.value))).props("outline").mark(
            f"{key}-export"
        )
        if pdf is not None:
            ui.button("Raport roczny PDF", icon="picture_as_pdf", on_click=lambda: pdf(int(year.value))).props(
                "outline"
            ).mark(f"{key}-pdf")
