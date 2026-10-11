"""Ustawienia > Instrumenty bez wyceny: the held Instruments without an automatic price, with the reason (spec 4.1,
issue #40). Clicking one opens its Instrument dialog, so the user can go through the imported Instruments and fill in
their Source Symbols; an Instrument leaves the list once a refresh gives it a Quote."""

from collections.abc import Callable
from dataclasses import dataclass

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.instruments import Instrument
from financial_app.domain.prices import source_reason
from financial_app.domain.valuation import Unpriced
from financial_app.sources.prices import unpriced_instruments


@dataclass
class UnpricedSection:
    """The Instrumenty bez wyceny card; ``refresh`` redraws it after an Instrument save or a price refresh."""

    engine: Engine

    def refresh(self) -> None:
        self.unpriced_list.refresh()

    def build(self, open_instrument: Callable[[Instrument], None]) -> None:
        """``open_instrument`` opens the Instrument dialog for a clicked row."""
        with ui.card().classes("w-full max-w-4xl"):
            ui.label("Instrumenty bez wyceny").classes("text-xl font-bold")
            ui.label(
                "Instrumenty z otwartą pozycją bez wyceny automatycznej. Kliknij instrument, uzupełnij symbol "
                "w źródle i odśwież wyceny."
            ).classes("text-sm text-gray-500")
            # The marker sits outside the refreshable list so it survives a refresh
            with ui.column().classes("w-full gap-0").mark("unpriced"):
                self.unpriced_list(open_instrument)

    @ui.refreshable_method
    def unpriced_list(self, open_instrument: Callable[[Instrument], None]) -> None:
        listed = unpriced_instruments(self.engine)
        if not listed:
            ui.label("Każdy instrument z otwartą pozycją ma wycenę automatyczną.").classes("text-gray-500")
        for unpriced in listed:
            _unpriced_row(unpriced, open_instrument)


def _unpriced_row(unpriced: Unpriced, open_instrument: Callable[[Instrument], None]) -> None:
    instrument = unpriced.instrument
    item = ui.item(on_click=lambda: open_instrument(instrument)).classes("w-full rounded border-b")
    with item.mark("unpriced-instrument"), ui.item_section():
        with ui.row().classes("items-center gap-2"):
            ui.label(instrument.name).classes("font-medium")
            ui.badge(instrument.asset_class_name).props("outline")
        ui.item_label(unpriced.reason).props("caption")
        for source, reason in unpriced.failures.items():
            ui.item_label(source_reason(source, reason)).props("caption").classes("pl-4")
