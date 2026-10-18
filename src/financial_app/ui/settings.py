"""The Ustawienia tab: Accounts, Asset Classes, Instruments, the price sources' settings, the sheet import (spec
section 5, issue #20), the Instruments without an automatic price (issue #40), Wygląd i widoczność (issue #155) and
clearing the data."""

from collections.abc import Callable, Mapping

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.instrument_search import InstrumentSearch
from financial_app.sources.nbp import NbpRates
from financial_app.sources.prices import PriceSource
from financial_app.ui.accounts import AccountsSection
from financial_app.ui.contribution_limits import ContributionLimitsSection
from financial_app.ui.import_sheet import SheetImportSection
from financial_app.ui.instruments import AssetClassesSection, InstrumentsSection
from financial_app.ui.price_sources import PriceSourcesSection
from financial_app.ui.recurring_rules import RecurringRulesSection
from financial_app.ui.reset import ClearDataSection
from financial_app.ui.unpriced import UnpricedSection
from financial_app.ui.visibility import Layout, VisibilitySection
from financial_app.ui.xtb_import import XtbImportSection


def build_settings_page(
    engine: Engine,
    rates: NbpRates,
    search: InstrumentSearch,
    sources: Mapping[str, PriceSource],
    unpriced: UnpricedSection,
    on_instruments_changed: Callable[[], None],
    on_transactions_changed: Callable[[], None] | None = None,
    on_account_deleted: Callable[[int], None] | None = None,
    on_rules_changed: Callable[[], None] | None = None,
    layout: Layout | None = None,
) -> None:
    """``unpriced`` is kept by the shell, which redraws it on the changes it declares; ``on_instruments_changed`` is
    called after an Instrument or Asset Class is saved; ``sources`` check the Source Symbols typed in the Instrument
    dialog. ``on_transactions_changed`` redraws the other tabs after an XTB Reconciliation is applied;
    ``on_account_deleted`` gets the id of an Account deleted in Konta; ``on_rules_changed`` redraws the Recurring
    Rules' Drafts after a rule or its skips change; ``layout`` is the window's hidden elements, which the shell
    redraws on."""
    ui.label("Ustawienia").classes("text-2xl font-bold")
    limits = ContributionLimitsSection(engine)
    rules = RecurringRulesSection(engine, rates.today, on_changed=on_rules_changed)
    accounts = AccountsSection(
        engine, on_deleted=on_account_deleted, on_changed=lambda: _all(limits.refresh, rules.refresh)
    )
    accounts.build()
    limits.build()
    rules.build()
    instruments = InstrumentsSection(engine, search, sources, on_changed=on_instruments_changed)
    asset_classes = AssetClassesSection(engine, on_changed=instruments.refresh)
    asset_classes.build()
    instruments.build()
    unpriced.build(open_instrument=instruments.open_dialog)
    PriceSourcesSection(engine).build()
    sheet_import = SheetImportSection(
        engine, rates, on_saved=limits.refresh, on_account_added=accounts.account_list.refresh
    )
    sheet_import.build()
    xtb_import = XtbImportSection(
        engine,
        rates,
        instruments.open_dialog,
        on_saved=lambda: _all(limits.refresh, on_transactions_changed),
        on_account_added=accounts.account_list.refresh,
    )
    xtb_import.build()

    def redraw() -> None:
        accounts.account_list.refresh()
        asset_classes.class_list.refresh()
        instruments.refresh()  # also redraws the Instruments without a price
        sheet_import.reset()
        xtb_import.reset()
        limits.refresh()
        rules.refresh()
        _all(on_rules_changed)  # the cleared rules' Drafts are no longer counted

    VisibilitySection(layout or Layout(engine)).build()
    ClearDataSection(engine, on_cleared=redraw).build()


def _all(*callbacks: Callable[[], None] | None) -> None:
    for callback in callbacks:
        if callback is not None:
            callback()
