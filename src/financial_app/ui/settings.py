"""The Ustawienia tab: Accounts, Asset Classes and Instruments (spec section 5)."""

from nicegui import ui
from sqlalchemy import Engine

from financial_app.ui.accounts import AccountsSection
from financial_app.ui.instruments import AssetClassesSection, InstrumentsSection


def build_settings_page(engine: Engine) -> None:
    ui.label("Ustawienia").classes("text-2xl font-bold")
    AccountsSection(engine).build()
    instruments = InstrumentsSection(engine)
    AssetClassesSection(engine, on_renamed=instruments.refresh).build()
    instruments.build()
