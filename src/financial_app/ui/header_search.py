"""The header search (issue #175): the user's own Instruments and treasury bond types (#185) listed while typing,
Search Results from the search services after a pause or on Enter, each opening its card."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from nicegui import run, ui
from sqlalchemy import Engine

from financial_app.domain.bonds import BondType
from financial_app.domain.commands import Command, in_command_mode, matching_commands
from financial_app.domain.formatting import format_count
from financial_app.domain.header_search import (
    BOND_TYPE_TERMS,
    SearchResult,
    group_results,
    matching_bond_types,
    matching_instruments,
)
from financial_app.domain.instrument_search import FoundListings, InstrumentSearch, InstrumentSearchError
from financial_app.domain.instruments import Instrument
from financial_app.persistence.instruments import list_instruments

# The search services are asked once this many characters are typed, after this pause in typing (seconds)
MIN_QUERY = 3
PAUSE = 0.5
# How many Search Results the list shows
FOUND_LIMIT = 8
# The list below the field: it scrolls, as ">" lists every command
_PANEL_CLASSES = "absolute top-full left-0 mt-1 w-[36rem] max-w-[90vw] max-h-[75vh] overflow-y-auto z-50 p-2"
# Ctrl+K anywhere, or "/" outside a field, puts the cursor in the search; in the browser, so that the key is not typed
_SHORTCUT_SCRIPT = """
<script>
document.addEventListener('keydown', (e) => {
  const inField = e.target.closest('input, textarea, select, [contenteditable]');
  if ((e.ctrlKey && e.key.toLowerCase() === 'k') || (e.key === '/' && !inField)) {
    const field = document.querySelector('.k-header-search input');
    if (field) { e.preventDefault(); field.focus(); }
  }
});
</script>
"""


@dataclass(frozen=True)
class PaletteCommand:
    """A command of the palette: what finds it (``domain/commands.py``), its icon and what ``run`` does."""

    command: Command
    icon: str
    run: Callable[[], object]


class HeaderSearch:
    """The search field with its list of results below it; ``open_card`` opens the Instrument Card on a row. It is
    also the command palette: ``commands`` the user may run, found by their words or all of them after ">"."""

    def __init__(
        self,
        engine: Engine,
        search: InstrumentSearch,
        open_card: Callable[[SearchResult | Instrument | BondType], None],
        commands: Sequence[PaletteCommand] = (),
    ) -> None:
        self.engine = engine
        self.search = search
        self.open_card = open_card
        self.commands = commands
        self.own: list[Instrument] = []
        self.bonds: list[BondType] = []
        self.matched: list[PaletteCommand] = []
        self.found: list[SearchResult] = []
        self.message = ""
        self.searched = ""  # the query the Search Results are of
        self.searching = False
        self.highlighted = 0
        self.pause: ui.timer | None = None

    def build(self) -> None:
        with ui.element("div").classes("relative w-[24rem] max-w-full shrink min-w-[10rem]") as self.box:
            # Short enough to fit the field whole
            self.field = ui.input(placeholder="Szukaj: symbol, ISIN, nazwa, > polecenie")
            self.field.props("dense outlined rounded clearable").classes("w-full k-header-search")
            self.field.mark("header-search")
            with self.field.add_slot("prepend"):
                ui.icon("search")
            self.field.on_value_change(self._typed)
            self.field.on("keydown.enter", self._entered)
            self.field.on("keydown.down", lambda: self._move(1))
            self.field.on("keydown.up", lambda: self._move(-1))
            self.field.on("keydown.esc", self._clear)
            with ui.card().classes(_PANEL_CLASSES) as self.panel:
                self.panel.mark("header-search-results")
                self.results()
            self.panel.visible = False
        ui.add_head_html(_SHORTCUT_SCRIPT)

    def _query(self) -> str:
        return (self.field.value or "").strip()

    def _typed(self) -> None:
        """Lists the own Instruments matching at once and asks the search services after a pause."""
        query = self._query()
        commands = {entry.command.key: entry for entry in self.commands}
        self.matched = [commands[c.key] for c in matching_commands([e.command for e in self.commands], query)]
        # After ">" only commands are listed, and the search services are not asked
        command_mode = in_command_mode(query)
        self.own = [] if command_mode else matching_instruments(list_instruments(self.engine), query)
        self.bonds = [] if command_mode else matching_bond_types(query)
        if query != self.searched:
            self.found, self.message = [], ""
        self.highlighted = 0
        if self.pause is not None:
            self.pause.cancel()
            self.pause = None
        if len(query) >= MIN_QUERY and query != self.searched and not command_mode:
            self.pause = ui.timer(PAUSE, self._find, once=True)
        self._show()

    async def _entered(self) -> None:
        """Enter opens the highlighted row: an own Instrument, a bond type or a command at once, a Search Result once
        the search services answered this query; otherwise it asks them now (never after ">")."""
        rows = self._rows()
        if in_command_mode(self._query()):
            if rows:
                self._open(rows[self.highlighted])
        elif self.highlighted < len(self.own) + len(self.bonds) + len(self.matched) or (
            self._query() == self.searched and rows
        ):
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
            # An empty FoundListings still carries its notes, so only None (shutting down) counts as nothing
            results = [] if answer is None else answer
            notes = results.notes if isinstance(results, FoundListings) else []
            message = " · ".join(notes) if results else " · ".join(["Nic nie znaleziono.", *notes])
        except InstrumentSearchError as error:
            results, message = [], str(error)
        finally:
            self.searching = False
        if query != self._query():  # typed on meanwhile, so these results are of an old query
            return
        self.found, self.message, self.searched = group_results(results)[:FOUND_LIMIT], message, query
        self._show()

    def _rows(self) -> list[SearchResult | Instrument | BondType | PaletteCommand]:
        return [*self.own, *self.bonds, *self.matched, *self.found]

    def _show(self) -> None:
        self.panel.visible = bool(self._query())
        self.results.refresh()

    def _open(self, subject: SearchResult | Instrument | BondType | PaletteCommand) -> None:
        self.panel.visible = False
        # A dialog is deleted with the element it was opened in, so not in a row the next results redraw away
        with self.box:
            if isinstance(subject, PaletteCommand):
                self.field.value = ""
                subject.run()
            else:
                self.open_card(subject)

    @ui.refreshable_method
    def results(self) -> None:
        index = 0
        if in_command_mode(self._query()):
            ui.label("Polecenia").classes("text-xs font-bold k-muted px-2 pt-1")
            if not self.matched:
                ui.label("Brak pasujących poleceń.").classes("text-sm k-muted px-2")
            for entry in self.matched:
                self._command_row(entry, index == self.highlighted)
                index += 1
            return
        if self.own:
            ui.label("Twoje instrumenty").classes("text-xs font-bold k-muted px-2 pt-1")
            for instrument in self.own:
                self._own_row(instrument, index == self.highlighted)
                index += 1
        if self.bonds:
            ui.label("Obligacje skarbowe").classes("text-xs font-bold k-muted px-2 pt-2")
            for bond_type in self.bonds:
                self._bond_row(bond_type, index == self.highlighted)
                index += 1
        if self.matched:
            ui.label("Polecenia").classes("text-xs font-bold k-muted px-2 pt-2")
            for entry in self.matched:
                self._command_row(entry, index == self.highlighted)
                index += 1
        ui.label("Znalezione").classes("text-xs font-bold k-muted px-2 pt-2")
        if self.searching:
            ui.spinner().classes("mx-2").mark("header-search-loading")
        if self.message:
            ui.label(self.message).classes("text-sm k-muted px-2").mark("header-search-message")
        if not self.searching and not self.found and not self.message:
            typed = format_count(MIN_QUERY, "znak", "znaki", "znaków")
            ui.label(f"Wpisz co najmniej {typed} i poczekaj chwilę albo naciśnij Enter.").classes(
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

    def _bond_row(self, bond_type: BondType, highlighted: bool) -> None:
        item = ui.item(on_click=lambda: self._open(bond_type)).classes(_row_classes(highlighted)).mark("bond-result")
        with item, ui.item_section():
            ui.item_label(bond_type.value)
            ui.item_label(f"obligacje {BOND_TYPE_TERMS[bond_type][0]}").props("caption")
        with item, ui.item_section().props("side"):
            ui.badge("Obligacja skarbowa").props("outline")

    def _command_row(self, entry: PaletteCommand, highlighted: bool) -> None:
        item = ui.item(on_click=lambda: self._open(entry)).props("dense").classes(_row_classes(highlighted))
        item.mark("command-result")
        with item, ui.item_section().props("avatar"):
            ui.icon(entry.icon)
        with item, ui.item_section():
            ui.item_label(entry.command.label)

    def _found_row(self, found: SearchResult, highlighted: bool) -> None:
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
