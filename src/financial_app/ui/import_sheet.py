"""Ustawienia > Import z arkusza: the Transakcje sheet, previewed before anything is saved (issue #20)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path as FilePath

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_date, format_pln, format_quantity
from financial_app.domain.spreadsheet_import import SheetError, SheetLine
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.sources.spreadsheet import (
    Decisions,
    NbpLookup,
    Preview,
    preview_import,
    read_sheet_lines,
    save_import,
)

NEW_INSTRUMENT = "new"
STATUS_LABELS = {
    "ok": "do zapisu",
    "duplicate": "już zaimportowana",
    "similar": "podobna do ręcznej, wstrzymana",
    "error": "błąd",
}


@dataclass
class SheetImportSection:
    """Reads the sheet, lets the user match its Konta and tickers, shows the preview, and saves on approval.

    ``on_saved`` lets the other tabs redraw the newly imported Transactions.
    """

    engine: Engine
    rates: NbpLookup
    on_saved: Callable[[], None] | None = None
    lines: list[SheetLine] = field(default_factory=list)
    accounts: dict[str, int] = field(default_factory=dict)
    instruments: dict[str, int | None] = field(default_factory=dict)
    keep_similar: set[str] = field(default_factory=set)

    def build(self) -> None:
        with ui.card().classes("w-full max-w-4xl"):
            ui.label("Import z arkusza Inwestomat").classes("text-xl font-bold")
            ui.label(
                "Wskaż kopię arkusza (.xlsx). Transakcje trafiają do bazy dopiero po zatwierdzeniu podglądu. "
                "Ponowny import tego samego pliku pomija zapisane już wiersze."
            ).classes("text-sm")
            path = ui.input("Plik arkusza (.xlsx)").classes("w-full").mark("import-path")
            ui.button("Podgląd", icon="visibility", on_click=lambda: self.load(path.value)).props("no-caps").mark(
                "import-preview"
            )
            self.result = ui.column().classes("w-full gap-2").mark("import-result")

    def load(self, text: str) -> None:
        try:
            self.lines = read_sheet_lines(FilePath(text.strip()))
        except SheetError as error:
            self.result.clear()
            ui.notify(str(error), type="negative")
            return
        self.accounts = {}
        self.instruments = {}
        self.keep_similar = set()
        self.render()

    def reset(self) -> None:
        """Forget the read sheet and the user's choices, e.g. after the data was cleared: they name removed ids."""
        self.lines = []
        self.accounts = {}
        self.instruments = {}
        self.keep_similar = set()
        self.result.clear()

    def render(self) -> None:
        preview = preview_import(self.engine, self.lines, self.rates, self._decisions())
        self.result.clear()
        with self.result:
            self._matching(preview)
            self._similar(preview)
            self._table(preview)
            ui.label(
                f"Do zapisu: {preview.to_save}, już zaimportowane (pominięte): {preview.duplicates}, "
                f"z błędami: {sum(item.status == 'error' for item in preview.lines)}."
            ).mark("import-summary")
            save = ui.button(
                f"Zapisz {preview.to_save} transakcji",
                icon="save",
                on_click=self.save,
            ).props("no-caps")
            save.mark("import-save")
            if preview.blocked or preview.to_save == 0:
                save.disable()

    def _decisions(self) -> Decisions:
        return Decisions(
            accounts=dict(self.accounts),
            instruments=dict(self.instruments),
            keep_similar=frozenset(self.keep_similar),
        )

    def _matching(self, preview: Preview) -> None:
        if preview.unmatched_accounts:
            ui.label("Konta z arkusza, których nie ma w aplikacji:").classes("font-bold")
            accounts = {account.id: account.name for account in list_accounts(self.engine)}
            for sheet_name in preview.unmatched_accounts:
                ui.select(
                    accounts,
                    label=f"Konto „{sheet_name}” to",
                    on_change=lambda e, name=sheet_name: self._choose_account(name, e.value),
                ).classes("w-full").mark(f"import-account-{sheet_name}")
        if preview.unmatched_instruments:
            ui.label("Tickery bez instrumentu w aplikacji (wybierz istniejący albo utwórz nowy):").classes("font-bold")
            instruments: dict[int | str, str] = {NEW_INSTRUMENT: "Nowy instrument"}
            instruments.update({instrument.id: instrument.name for instrument in list_instruments(self.engine)})
            for name in preview.unmatched_instruments:
                ui.select(
                    instruments,
                    value=NEW_INSTRUMENT,
                    label=f"Ticker „{name}” to",
                    on_change=lambda e, ticker=name: self._choose_instrument(ticker, e.value),
                ).classes("w-full").mark(f"import-instrument-{name}")

    def _similar(self, preview: Preview) -> None:
        if preview.held_back:
            ui.label(
                "Te wiersze wyglądają jak transakcje wpisane ręcznie. Zaznacz, które mimo to zaimportować:"
            ).classes("font-bold")
        for item in preview.held_back:
            ui.checkbox(
                f"Wiersz {item.line.row}: {item.line.ticker}, {format_date(item.line.day)} — {item.message}",
                value=item.external_id in self.keep_similar,
                on_change=lambda e, key=item.external_id: self._keep(key, e.value),
            ).mark(f"import-keep-{item.line.row}")

    def _keep(self, external_id: str, keep: bool) -> None:
        if keep:
            self.keep_similar.add(external_id)
        else:
            self.keep_similar.discard(external_id)
        self.render()

    def _table(self, preview: Preview) -> None:
        rows = [
            {
                "row": item.line.row,
                "date": format_date(item.line.day),
                "account": item.line.account,
                "ticker": item.line.ticker,
                "kind": item.line.kind,
                "quantity": format_quantity(item.line.quantity) if item.line.quantity is not None else "",
                "total": format_pln(item.draft.actual_amount if item.draft else item.line.total),
                "status": STATUS_LABELS[item.status] + (f": {item.message}" if item.message else ""),
            }
            for item in preview.lines
        ]
        columns = [
            {"name": "row", "label": "Wiersz", "field": "row", "align": "left"},
            {"name": "date", "label": "Data", "field": "date", "align": "left"},
            {"name": "account", "label": "Konto", "field": "account", "align": "left"},
            {"name": "ticker", "label": "Ticker", "field": "ticker", "align": "left"},
            {"name": "kind", "label": "Rodzaj", "field": "kind", "align": "left"},
            {"name": "quantity", "label": "Liczba", "field": "quantity", "align": "right"},
            {"name": "total", "label": "Total PLN", "field": "total", "align": "right"},
            {"name": "status", "label": "Status", "field": "status", "align": "left"},
        ]
        ui.table(columns=columns, rows=rows, row_key="row").classes("w-full").mark("import-table")

    def _choose_account(self, sheet_name: str, account_id: int) -> None:
        self.accounts[sheet_name] = account_id
        self.render()

    def _choose_instrument(self, ticker: str, choice: int | str) -> None:
        self.instruments[ticker] = None if choice == NEW_INSTRUMENT else int(choice)
        self.render()

    def save(self) -> None:
        try:
            saved = save_import(self.engine, self.lines, self.rates, self._decisions())
        except SheetError as error:
            ui.notify(str(error), type="negative")
            self.render()
            return
        ui.notify(f"Zaimportowano transakcje: {saved.to_save}.", type="positive")
        if self.on_saved is not None:
            self.on_saved()
        self.render()
