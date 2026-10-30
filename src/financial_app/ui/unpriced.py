"""Ustawienia > Instrumenty bez wyceny: the held Instruments without an automatic price, with the reason (spec 4.1,
issue #40). Clicking one opens its Instrument dialog, so the user can go through the imported Instruments and fill in
their Source Symbols; its help button opens the price source help window (issue #274). An Instrument leaves the list
once a refresh gives it a Quote."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.instruments import Instrument
from financial_app.domain.prices import source_reason
from financial_app.domain.valuation import Unpriced
from financial_app.sources.prices import PriceSource, unpriced_instruments
from financial_app.ui.changes import Change
from financial_app.ui.price_source_guide import PriceSourceGuide


@dataclass
class UnpricedSection:
    """The Instrumenty bez wyceny card; ``refresh`` redraws it after a Transaction save, a price refresh or an
    Instrument change. Bond Series are never listed, so bond data leaves it alone. ``sources`` check the symbols
    typed in the price source help window."""

    # The changes it redraws on (ui/changes.py)
    CHANGES = frozenset({Change.TRANSACTIONS, Change.PRICES, Change.INSTRUMENTS})

    engine: Engine
    sources: Mapping[str, PriceSource] = field(compare=False)
    # The card, which a redraw of the list never removes: the help windows are opened in it
    box: ui.element | None = field(default=None, compare=False)

    def refresh(self) -> None:
        self.unpriced_list.refresh()

    def build(self, open_instrument: Callable[[Instrument], None], on_saved: Callable[[], object]) -> None:
        """``open_instrument`` opens the Instrument dialog for a clicked row; ``on_saved`` runs after the help window
        saved an Instrument."""
        with ui.card().classes("w-full max-w-4xl") as self.box:
            ui.label("Instrumenty bez wyceny").classes("text-xl font-bold")
            ui.label(
                "Instrumenty z otwartą pozycją bez wyceny automatycznej. Kliknij instrument, uzupełnij symbol "
                "w źródle i odśwież wyceny, albo otwórz pomoc (?), która przeprowadzi Cię przez wybór źródła."
            ).classes("text-sm k-muted")
            # The marker sits outside the refreshable list so it survives a refresh
            with ui.column().classes("w-full gap-0").mark("unpriced"):
                self.unpriced_list(open_instrument, on_saved)

    @ui.refreshable_method
    def unpriced_list(self, open_instrument: Callable[[Instrument], None], on_saved: Callable[[], object]) -> None:
        listed = unpriced_instruments(self.engine)
        if not listed:
            ui.label("Każdy instrument z otwartą pozycją ma wycenę automatyczną.").classes("k-muted")
        for unpriced in listed:
            with ui.row().classes("w-full items-center no-wrap gap-0 border-b"):
                _unpriced_row(unpriced, open_instrument)
                ui.button(icon="help_outline", on_click=lambda i=unpriced.instrument: self._guide(i, on_saved)).props(
                    f'flat round aria-label="Pomoc w wyborze źródła ceny: {unpriced.instrument.name}"'
                ).mark("unpriced-guide")

    def _guide(self, instrument: Instrument, on_saved: Callable[[], object]) -> None:
        assert self.box is not None
        with self.box:
            PriceSourceGuide(self.engine, self.sources, instrument, on_saved).open()


def _unpriced_row(unpriced: Unpriced, open_instrument: Callable[[Instrument], None]) -> None:
    instrument = unpriced.instrument
    item = ui.item(on_click=lambda: open_instrument(instrument)).classes("grow rounded")
    with item.mark("unpriced-instrument"), ui.item_section():
        with ui.row().classes("items-center gap-2"):
            ui.label(instrument.name).classes("font-medium")
            ui.badge(instrument.asset_class_name).props("outline")
        ui.item_label(unpriced.reason).props("caption")
        for source, reason in unpriced.failures.items():
            ui.item_label(source_reason(source, reason)).props("caption").classes("pl-4")
