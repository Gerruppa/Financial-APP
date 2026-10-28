"""The Ustawienia tab: the User, Accounts, Asset Classes, Instruments, the price sources' settings, the sheet import
(spec section 5, issue #20), the Instruments without an automatic price (issue #40), Wygląd i widoczność (issue #155)
and clearing the data."""

from collections.abc import Callable, Mapping

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.instrument_search import InstrumentSearch
from financial_app.sources.nbp import NbpRates
from financial_app.sources.prices import PriceSource
from financial_app.ui.accounts import AccountsSection
from financial_app.ui.contribution_limits import ContributionLimitsSection
from financial_app.ui.crypto_import import CryptoImportSection
from financial_app.ui.import_sheet import SheetImportSection
from financial_app.ui.instruments import AssetClassesSection, InstrumentsSection
from financial_app.ui.recurring_rules import RecurringRulesSection
from financial_app.ui.reset import ClearDataSection
from financial_app.ui.theme import ThemeChoice
from financial_app.ui.unpriced import UnpricedSection
from financial_app.ui.user_section import UserSection
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
    theme: ThemeChoice | None = None,
    user_section: UserSection | None = None,
) -> None:
    """``unpriced`` is kept by the shell, which redraws it on the changes it declares; ``on_instruments_changed`` is
    called after an Instrument or Asset Class is saved; ``sources`` check the Source Symbols typed in the Instrument
    dialog. ``on_transactions_changed`` redraws the other tabs after an XTB Reconciliation is applied;
    ``on_account_deleted`` gets the id of an Account deleted in Konta; ``on_rules_changed`` redraws the Recurring
    Rules' Drafts after a rule or its skips change; ``layout`` is the window's hidden elements, which the shell
    redraws on, and ``theme`` its Theme, which the shell reloads the window on."""
    ui.label("Ustawienia").classes("text-2xl font-bold")
    limits = ContributionLimitsSection(engine)
    rules = RecurringRulesSection(engine, rates.today, on_changed=on_rules_changed)
    accounts = AccountsSection(
        engine, on_deleted=on_account_deleted, on_changed=lambda: _all(limits.refresh, rules.refresh)
    )
    instruments = InstrumentsSection(engine, search, sources, on_changed=on_instruments_changed)
    asset_classes = AssetClassesSection(engine, on_changed=instruments.refresh)
    sheet_import = SheetImportSection(
        engine, rates, on_saved=limits.refresh, on_account_added=accounts.account_list.refresh
    )
    xtb_import = XtbImportSection(
        engine,
        rates,
        instruments.open_dialog,
        on_saved=lambda: _all(limits.refresh, on_transactions_changed),
        on_account_added=accounts.account_list.refresh,
    )

    crypto_import = CryptoImportSection(
        engine,
        rates,
        instruments.open_dialog,
        on_saved=lambda: _all(limits.refresh, on_transactions_changed),
        on_account_added=accounts.account_list.refresh,
    )

    def redraw() -> None:
        accounts.account_list.refresh()
        asset_classes.class_list.refresh()
        instruments.refresh()  # also redraws the Instruments without a price
        sheet_import.reset()
        xtb_import.reset()
        crypto_import.reset()
        limits.refresh()
        rules.refresh()
        _all(on_rules_changed)  # the cleared rules' Drafts are no longer counted

    def build_instruments() -> None:
        instruments.build()
        unpriced.build(open_instrument=instruments.open_dialog)

    def build_imports() -> None:
        sheet_import.build()
        xtb_import.build()
        crypto_import.build()

    # One button per section: only the chosen section is on screen, so the page stays short.
    sections: list[tuple[str, str, Callable[[], None]]] = [
        ("accounts", "Konta", accounts.build),
        ("limits", "Limity i reguły", lambda: _all(limits.build, rules.build)),
        ("asset-classes", "Klasy aktywów", asset_classes.build),
        ("instruments", "Instrumenty", build_instruments),
        ("import", "Import", build_imports),
        (
            "appearance",
            "Wygląd i widoczność",
            VisibilitySection(layout or Layout(engine), theme or ThemeChoice(engine)).build,
        ),
        ("data", "Wyczyść dane", ClearDataSection(engine, on_cleared=redraw).build),
    ]
    if user_section is not None:
        sections.insert(0, ("user", "Użytkownik", user_section.build))
    with ui.tabs().props("dense align=left shrink").classes("w-full") as tabs:
        for key, title, _ in sections:
            ui.tab(key, label=title).mark(f"settings-section-{key}")
    with ui.tab_panels(tabs, value=sections[0][0]).props("keep-alive").classes("w-full"):
        for key, _, build in sections:
            with ui.tab_panel(key).classes("p-0"):
                build()


def _all(*callbacks: Callable[[], None] | None) -> None:
    for callback in callbacks:
        if callback is not None:
            callback()
