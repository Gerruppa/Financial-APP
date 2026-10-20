"""The header search (issue #175): the user's own Instruments listed while typing, Search Results from the search
services after a pause or on Enter, each opening its Instrument Card."""

from collections.abc import Callable

from nicegui import events, run, ui
from sqlalchemy import Engine

from financial_app.domain.instrument_card import FoundInstrument, group_results, matching_instruments
from financial_app.domain.instrument_search import InstrumentSearch, InstrumentSearchError, SearchResults
from financial_app.domain.instruments import Instrument
from financial_app.persistence.instruments import list_instruments

# The search services are asked once this many characters are typed, after this pause in typing (seconds)
MIN_QUERY = 3
PAUSE = 0.5
# How many Search Results the list shows
FOUND_LIMIT = 8


class HeaderSearch:
    """The search field with its list of results below it; ``open_card`` opens the Instrument Card on a row."""

    def __init__(
        self, engine: Engine, search: InstrumentSearch, open_card: Callable[[FoundInstrument | Instrument], None]
    ) -> None:
        self.engine = engine
        self.search = search
        self.open_card = open_card
        self.own: list[Instrument] = []
        self.found: list[FoundInstrument] = []
        self.message = ""
        self.searched = ""  # the query the Search Results are of
        self.searching = False
        self.highlighted = 0
        self.pause: ui.timer | None = None

    def build(self) -> None:
        with ui.element("div").classes("relative w-[28rem] max-w-full"):
            self.field = ui.input(placeholder="Szukaj instrumentu: ticker, ISIN, nazwa")
            self.field.props("dense outlined rounded clearable").classes("w-full")
            self.field.mark("header-search")
            with self.field.add_slot("prepend"):
                ui.icon("search")
            self.field.on_value_change(self._typed)
            self.field.on("keydown.enter", self._entered)
            self.field.on("keydown.down", lambda: self._move(1))
            self.field.on("keydown.up", lambda: self._move(-1))
            self.field.on("keydown.esc", self._clear)
            with ui.card().classes("absolute top-full left-0 mt-1 w-[36rem] max-w-[90vw] z-50 p-2") as self.panel:
                self.panel.mark("header-search-results")
                self.results()
            self.panel.visible = False
        # Ctrl+K or "/" outside a field puts the cursor in the search
        ui.keyboard(on_key=self._shortcut)

    def _shortcut(self, event: events.KeyEventArguments) -> None:
        if event.action.keydown and (event.key == "/" or (event.key == "k" and event.modifiers.ctrl)):
            self.field.run_method("focus")

    def _query(self) -> str:
        return (self.field.value or "").strip()

    def _typed(self) -> None:
        """Lists the own Instruments matching at once and asks the search services after a pause."""
        query = self._query()
        self.own = matching_instruments(list_instruments(self.engine), query)
        if query != self.searched:
            self.found, self.message = [], ""
        self.highlighted = 0
        if self.pause is not None:
            self.pause.cancel()
            self.pause = None
        if len(query) >= MIN_QUERY and query != self.searched:
            self.pause = ui.timer(PAUSE, self._find, once=True)
        self._show()

    async def _entered(self) -> None:
        """Enter opens the highlighted row once the search services answered this query, else asks them now."""
        rows = self._rows()
        if self._query() == self.searched and rows:
            self._open(rows[self.highlighted])
        else:
            await self._find()

    def _move(self, step: int) -> None:
        rows = self._rows()
        if rows:
            self.highlighted = (self.highlighted + step) % len(rows)
            self.results.refresh()

    def _clear(self) -> None:
        self.field.value = ""
        self.panel.visible = False

    async def _find(self) -> None:
        if self.pause is not None:
            self.pause.cancel()
            self.pause = None
        query = self._query()
        if not query:
            return
        self.searching = True
        self._show()
        try:
            # The search answers over the network, so the window keeps working meanwhile
            answer = await run.io_bound(self.search.search, query)
            # An empty SearchResults still carries its notes, so only None (shutting down) counts as nothing
            results = [] if answer is None else answer
            notes = results.notes if isinstance(results, SearchResults) else []
            message = " · ".join(notes) if results else " · ".join(["Nic nie znaleziono.", *notes])
        except InstrumentSearchError as error:
            results, message = [], str(error)
        finally:
            self.searching = False
        if query != self._query():  # typed on meanwhile, so these results are of an old query
            return
        self.found, self.message, self.searched = group_results(results)[:FOUND_LIMIT], message, query
        self._show()

    def _rows(self) -> list[FoundInstrument | Instrument]:
        return [*self.own, *self.found]

    def _show(self) -> None:
        self.panel.visible = bool(self._query())
        self.results.refresh()

    def _open(self, subject: FoundInstrument | Instrument) -> None:
        self.panel.visible = False
        self.open_card(subject)

    @ui.refreshable_method
    def results(self) -> None:
        index = 0
        if self.own:
            ui.label("Twoje instrumenty").classes("text-xs font-bold k-muted px-2 pt-1")
            for instrument in self.own:
                self._own_row(instrument, index == self.highlighted)
                index += 1
        ui.label("Znalezione").classes("text-xs font-bold k-muted px-2 pt-2")
        if self.searching:
            ui.spinner().classes("mx-2").mark("header-search-loading")
        if self.message:
            ui.label(self.message).classes("text-sm k-muted px-2").mark("header-search-message")
        if not self.searching and not self.found and not self.message:
            ui.label(f"Wpisz co najmniej {MIN_QUERY} znaki i poczekaj chwilę albo naciśnij Enter.").classes(
                "text-sm k-muted px-2"
            )
        for found in self.found:
            self._found_row(found, index == self.highlighted)
            index += 1

    def _own_row(self, instrument: Instrument, highlighted: bool) -> None:
        item = ui.item(on_click=lambda: self._open(instrument)).classes(_row_classes(highlighted)).mark("own-result")
        with item, ui.item_section():
            ui.item_label(instrument.name)
            details = [instrument.isin, *instrument.source_symbols.values(), instrument.quote_currency]
            ui.item_label(" · ".join(d for d in details if d)).props("caption")
        with item, ui.item_section().props("side"):
            ui.badge(instrument.asset_class_name).props("outline")

    def _found_row(self, found: FoundInstrument, highlighted: bool) -> None:
        item = ui.item(on_click=lambda: self._open(found)).classes(_row_classes(highlighted)).mark("found-result")
        with item, ui.item_section():
            ui.item_label(found.name)
            with ui.row().classes("items-center gap-1"):
                if found.isin:
                    ui.badge(found.isin).props("outline color=grey")
                for listing in found.listings:
                    ui.badge(listing.symbol).props("color=primary")
        with item, ui.item_section().props("side"), ui.row().classes("gap-1 no-wrap"):
            for name in [*found.asset_classes, *found.sources]:
                ui.badge(name).props("outline")


def _row_classes(highlighted: bool) -> str:
    return "w-full rounded k-hover" + (" k-highlight" if highlighted else "")
