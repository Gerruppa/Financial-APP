"""The Ustawienia tab: Accounts, Asset Classes, Instruments, the price sources' settings, the sheet import (spec
section 5, issue #20), the Instruments without an automatic price (issue #40) and clearing the data."""

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.instrument_search import InstrumentSearch
from financial_app.sources.nbp import NbpRates
from financial_app.ui.accounts import AccountsSection
from financial_app.ui.import_sheet import SheetImportSection
from financial_app.ui.instruments import AssetClassesSection, InstrumentsSection
from financial_app.ui.price_sources import PriceSourcesSection
from financial_app.ui.reset import ClearDataSection
from financial_app.ui.unpriced import UnpricedSection


def build_settings_page(engine: Engine, rates: NbpRates, search: InstrumentSearch, unpriced: UnpricedSection) -> None:
    """``unpriced`` is kept by the shell, which redraws it after a price refresh."""
    ui.label("Ustawienia").classes("text-2xl font-bold")
    accounts = AccountsSection(engine)
    accounts.build()
    instruments = InstrumentsSection(engine, search, on_changed=unpriced.refresh)
    asset_classes = AssetClassesSection(engine, on_renamed=instruments.refresh)
    asset_classes.build()
    instruments.build()
    unpriced.build(open_instrument=instruments.open_dialog)
    PriceSourcesSection(engine).build()
    sheet_import = SheetImportSection(engine, rates)
    sheet_import.build()

    def redraw() -> None:
        accounts.account_list.refresh()
        asset_classes.class_list.refresh()
        instruments.refresh()  # also redraws the Instruments without a price
        sheet_import.reset()

    ClearDataSection(engine, on_cleared=redraw).build()
