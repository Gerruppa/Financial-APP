"""The Ustawienia tab: Accounts, Asset Classes, Instruments, the sheet import (spec section 5, issue #20) and clearing
the data."""

from nicegui import ui
from sqlalchemy import Engine

from financial_app.sources.nbp import NbpRates
from financial_app.ui.accounts import AccountsSection
from financial_app.ui.import_sheet import SheetImportSection
from financial_app.ui.instruments import AssetClassesSection, InstrumentsSection
from financial_app.ui.reset import ClearDataSection


def build_settings_page(engine: Engine, rates: NbpRates) -> None:
    ui.label("Ustawienia").classes("text-2xl font-bold")
    accounts = AccountsSection(engine)
    accounts.build()
    instruments = InstrumentsSection(engine)
    asset_classes = AssetClassesSection(engine, on_renamed=instruments.refresh)
    asset_classes.build()
    instruments.build()
    sheet_import = SheetImportSection(engine, rates)
    sheet_import.build()

    def redraw() -> None:
        accounts.account_list.refresh()
        asset_classes.class_list.refresh()
        instruments.refresh()
        sheet_import.reset()

    ClearDataSection(engine, on_cleared=redraw).build()
