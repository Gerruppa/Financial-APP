"""Ustawienia > Źródła wycen: the user's Stooq API key, needed for price history (issue #33)."""

from nicegui import ui
from sqlalchemy import Engine

from financial_app.persistence.settings import STOOQ_API_KEY, load_setting, save_setting


def build_price_sources_section(engine: Engine) -> None:
    with ui.card().classes("w-full max-w-4xl"):
        ui.label("Źródła wycen").classes("text-xl font-bold")
        ui.label(
            "Stooq dostarcza historię notowań i indeksów (np. WIG) do wykresów. Pobieranie wymaga osobistego klucza "
            "API: wejdź na stooq.com/q/d/?s=wig&get_apikey, przepisz kod z obrazka i wklej tu otrzymany klucz."
        ).classes("text-sm")
        with ui.row().classes("w-full items-center no-wrap"):
            key = ui.input("Klucz API Stooq", value=load_setting(engine, STOOQ_API_KEY) or "", password=True)
            key.props("password-toggle-button").classes("grow").mark("stooq-api-key")

            def save() -> None:
                save_setting(engine, STOOQ_API_KEY, key.value.strip())
                ui.notify("Zapisano klucz API Stooq.", type="positive")

            ui.button("Ustaw klucz", on_click=save).props("no-caps").mark("save-stooq-api-key")
