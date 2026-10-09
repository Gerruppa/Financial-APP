"""The Ustawienia tab: Accounts, Asset Classes, Instruments and the sheet import (spec section 5, issue #20)."""

from nicegui import ui
from sqlalchemy import Engine

from financial_app.sources.nbp import NbpRates
from financial_app.ui.accounts import AccountsSection
from financial_app.ui.import_sheet import SheetImportSection
from financial_app.ui.instruments import AssetClassesSection, InstrumentsSection


def build_settings_page(engine: Engine, rates: NbpRates) -> None:
    ui.label("Ustawienia").classes("text-2xl font-bold")
    AccountsSection(engine).build()
    instruments = InstrumentsSection(engine)
    AssetClassesSection(engine, on_renamed=instruments.refresh).build()
    instruments.build()
    SheetImportSection(engine, rates).build()
