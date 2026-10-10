"""Ustawienia > Źródła wycen: the user's Stooq API key, needed for price history (issue #33)."""

from dataclasses import dataclass

from nicegui import ui
from sqlalchemy import Engine

from financial_app.persistence.settings import STOOQ_API_KEY, load_setting, save_setting


@dataclass
class PriceSourcesSection:
    engine: Engine

    def build(self) -> None:
        with ui.card().classes("w-full max-w-4xl"):
            ui.label("Źródła wycen").classes("text-xl font-bold")
            ui.label(
                "Stooq dostarcza historię notowań i indeksów (np. WIG) do wykresów. Pobieranie wymaga osobistego "
                "klucza API: wejdź na stooq.com/q/d/?s=wig&get_apikey, przepisz kod z obrazka i wklej tu otrzymany "
                "klucz."
            ).classes("text-sm")
            with ui.row().classes("w-full items-center no-wrap"):
                self.key = ui.input(
                    "Klucz API Stooq", value=load_setting(self.engine, STOOQ_API_KEY) or "", password=True
                )
                self.key.props("password-toggle-button").classes("grow").mark("stooq-api-key")
                ui.button("Ustaw klucz", on_click=self.save).props("no-caps").mark("save-stooq-api-key")

    def save(self) -> None:
        save_setting(self.engine, STOOQ_API_KEY, self.key.value.strip())
        ui.notify("Zapisano klucz API Stooq.", type="positive")
