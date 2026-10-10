"""Ustawienia > Wyczyść dane: removes the whole portfolio after a warning and a typed confirmation."""

from collections.abc import Callable
from dataclasses import dataclass

from nicegui import ui
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from financial_app.persistence.reset import clear_portfolio, portfolio_counts

CONFIRMATION_PHRASE = "USUŃ WSZYSTKO"


@dataclass
class ClearDataSection:
    """The Wyczyść dane card; ``on_cleared`` lets the other sections redraw their now empty lists."""

    engine: Engine
    on_cleared: Callable[[], None]

    def build(self) -> None:
        with ui.card().classes("w-full max-w-4xl border border-red-300"):
            ui.label("Wyczyść dane").classes("text-xl font-bold text-negative")
            ui.label(
                "Usuwa wszystkie Konta, Instrumenty i Transakcje, a Klasy aktywów przywraca do domyślnych. "
                "Przydatne do testów albo przed założeniem nowego portfela."
            ).classes("text-sm")
            ui.button("Wyczyść wszystkie dane", icon="delete_forever", on_click=self.warn).props(
                "color=negative no-caps"
            ).mark("clear-data")

    def warn(self) -> None:
        """First step: say what will be removed."""
        counts = portfolio_counts(self.engine)
        dialog = ui.dialog()
        dialog.on("hide", dialog.delete)

        def next_step() -> None:
            dialog.close()
            self.ask_for_phrase()

        with dialog, ui.card():
            ui.label("Wyczyścić wszystkie dane?").classes("text-lg font-bold text-negative")
            ui.label("Zostaną usunięte:")
            with ui.column().classes("gap-0 pl-4"):
                ui.label(f"Konta: {counts.accounts}")
                ui.label(f"Instrumenty: {counts.instruments}")
                ui.label(f"Transakcje: {counts.transactions}")
            ui.label("Klasy aktywów wrócą do 12 domyślnych. Kursy NBP zostają.").classes("text-sm")
            ui.label("Przed usunięciem kopia bazy trafi do folderu kopii zapasowych.").classes("text-sm text-gray-600")
            with ui.row().classes("w-full justify-end"):
                ui.button("Anuluj", on_click=dialog.close).props("flat").mark("clear-data-cancel")
                ui.button("Dalej", on_click=next_step).props("color=negative").mark("clear-data-next")
        dialog.open()

    def ask_for_phrase(self) -> None:
        """Second step: the user types the phrase before the data goes."""
        dialog = ui.dialog()
        dialog.on("hide", dialog.delete)

        def clear() -> None:
            dialog.close()
            try:
                backup = clear_portfolio(self.engine)
            except (OSError, SQLAlchemyError) as exc:
                ui.notify(f"Nie udało się wyczyścić danych: {exc}", type="negative")
                return
            where = f" Kopia bazy: {backup.name}." if backup is not None else ""
            ui.notify(f"Wyczyszczono dane.{where}", type="positive", timeout=10000)
            self.on_cleared()

        with dialog, ui.card():
            ui.label("Tej operacji nie można cofnąć w aplikacji").classes("text-lg font-bold text-negative")
            with ui.row().classes("items-baseline gap-1"):
                ui.label("Aby potwierdzić, wpisz:")
                ui.label(CONFIRMATION_PHRASE).classes("font-mono font-bold")
            phrase = ui.input().classes("w-full").mark("clear-data-phrase")
            with ui.row().classes("w-full justify-end"):
                ui.button("Anuluj", on_click=dialog.close).props("flat").mark("clear-data-phrase-cancel")
                confirm = ui.button("Wyczyść dane", on_click=clear).props("color=negative").mark("clear-data-confirm")
            confirm.disable()
            phrase.on_value_change(lambda e: confirm.set_enabled((e.value or "").strip() == CONFIRMATION_PHRASE))
        dialog.open()
