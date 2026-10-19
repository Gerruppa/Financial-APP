"""App shell (issues #1 and #174): left menu with the logo, header with View Scope and Theme, "+" button."""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nicegui import background_tasks, run, ui
from sqlalchemy import Engine

from financial_app import __version__
from financial_app.domain.formatting import format_datetime
from financial_app.domain.instrument_search import CombinedSearch, InstrumentSearch
from financial_app.domain.prices import ANALIZY, BANKIER, BOSSA, SOURCE_NAMES, YAHOO, refresh_due, source_reason
from financial_app.domain.themes import Theme
from financial_app.domain.ui_visibility import tab_key
from financial_app.persistence.bond_data import bond_data_statuses
from financial_app.persistence.quotes import last_successful_refresh
from financial_app.sources.analizy import AnalizySearch, AnalizySource
from financial_app.sources.bankier import BankierSource
from financial_app.sources.bond_data import BondDataSources, bond_data_due, refresh_bond_data
from financial_app.sources.bossa import BossaSource
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates
from financial_app.sources.portfolio_history import PortfolioHistory
from financial_app.sources.prices import PriceSource, RefreshResult, last_refresh, refresh_prices, refresh_summary
from financial_app.sources.valuation_snapshots import take_snapshot
from financial_app.sources.yahoo import YahooSearch, YahooSource
from financial_app.ui.benchmarks import BenchmarksPage
from financial_app.ui.bond_data import bond_data_status
from financial_app.ui.bond_drafts import drafts_count
from financial_app.ui.bonds import BondsPage
from financial_app.ui.changes import Change, ChangeEvents, Redrawing
from financial_app.ui.dashboard import DashboardPage
from financial_app.ui.dialogs import install_movable_dialogs
from financial_app.ui.help import HELP_PATH, build_help_page
from financial_app.ui.history import history_status, shared_history
from financial_app.ui.multi_asset import MultiAssetPage
from financial_app.ui.passive_income import PassiveIncomePage
from financial_app.ui.periods import PeriodChoice
from financial_app.ui.portfolio import PortfolioPage
from financial_app.ui.recurring_drafts import recurring_drafts_count
from financial_app.ui.results import ResultsPage
from financial_app.ui.sale_summary import SaleSummaryPage
from financial_app.ui.sayings import menu_saying
from financial_app.ui.settings import build_settings_page
from financial_app.ui.strategy import PlannedDeposit, StrategyPage, out_of_band_notice
from financial_app.ui.theme import ThemeChoice, apply_theme
from financial_app.ui.transaction_dialog import open_transaction_dialog
from financial_app.ui.transactions import TransactionsPage
from financial_app.ui.unpriced import UnpricedSection
from financial_app.ui.view_scope import ScopeSwitcher, ViewScope, breadcrumbs
from financial_app.ui.visibility import Layout

APP_TITLE = "KAPITA"
ASSETS_DIR = Path(__file__).parent / "assets"
APP_ICON = ASSETS_DIR / "kapita.ico"
APP_LOGO = ASSETS_DIR / "kapita.png"


@dataclass(frozen=True)
class Tab:
    label: str
    path: str
    icon: str


SETTINGS_PATH = "/ustawienia"
TABS = [
    Tab("Dashboard", "/", "dashboard"),
    Tab("Wyniki", "/wyniki", "insights"),
    Tab("Portfolio", "/portfolio", "account_balance_wallet"),
    Tab("Transakcje", "/transakcje", "receipt_long"),
    Tab("Strategie inwestycyjne", "/strategie", "flag"),
    Tab("Dochód stały", "/obligacje", "savings"),
    Tab("Multi-asset", "/multi-asset", "pie_chart"),
    Tab("Benchmarki", "/benchmarki", "compare_arrows"),
    Tab("Podsumowanie sprzedaży", "/sprzedaz", "sell"),
    Tab("Dochód pasywny", "/dochod-pasywny", "payments"),
    Tab("Ustawienia", SETTINGS_PATH, "settings"),
    Tab("Pomoc", HELP_PATH, "help"),
]
# The tabs without the "+" transaction button (L-28, issue #156)
WITHOUT_ADD_BUTTON = frozenset({SETTINGS_PATH, HELP_PATH})

# The refresh running on each database, shared by every window, so that a reloaded window joins it instead of starting
# another; ``None`` from it means the app is shutting down
_running_refreshes: dict[Engine, asyncio.Future[RefreshResult | None]] = {}


def build_shell(
    engine: Engine,
    rates: NbpRates | None = None,
    sources: Mapping[str, PriceSource] | None = None,
    refresh_at_start: bool = False,
    now: Callable[[], datetime] = datetime.now,
    search: InstrumentSearch | None = None,
    history: PortfolioHistory | None = None,
    bond_data: BondDataSources | None = None,
) -> None:
    """Build the whole window; tabs are client-side sub-pages backed by the database at ``engine``.

    ``rates`` gives NBP Rates (by default from the NBP API through the cache in that database) and ``sources`` the
    Price Sources by their key (by default the real ones). With ``refresh_at_start`` the prices are refreshed in the
    background once the window is open, when they are due at ``now`` (spec 4.1). ``search`` finds Instruments for
    the Instrument dialog (by default Yahoo and analizy.pl together). ``history`` is the database's History (by
    default fetched from Yahoo and Stooq, computed in the process pool); with ``refresh_at_start`` its missing days are
    fetched after the price refresh. ``bond_data`` gives the MF file, GUS CPI and the NBP reference rate, fetched
    with the price refresh at most once a day (by default the real sources, or none when test ``sources`` are given).
    """
    rates = rates or NbpRates(engine)
    if sources is None:
        bond_data = bond_data or BondDataSources.real()
        sources = {YAHOO: YahooSource(), BOSSA: BossaSource(), ANALIZY: AnalizySource(), BANKIER: BankierSource()}
    search = search or CombinedSearch({SOURCE_NAMES[YAHOO]: YahooSearch(), SOURCE_NAMES[ANALIZY]: AnalizySearch()})
    install_movable_dialogs()
    events = ChangeEvents()
    shared = shared_history(
        engine, lambda: history or PortfolioHistory(engine, QuoteHistory(engine), rates, lambda: now().date())
    )
    scope = ViewScope(engine)
    period = PeriodChoice(engine, lambda: now().date())
    planned = PlannedDeposit()
    layout = Layout(engine)
    layout.on_change(lambda: events.publish(Change.LAYOUT))
    theme = ThemeChoice(engine)
    dashboard_page = DashboardPage(engine, rates, scope, period, lambda: shared.days, layout, planned)
    strategy_page = StrategyPage(engine, rates, scope, planned)
    results_page = ResultsPage(engine, scope, period, lambda: shared.days)
    transactions_page = TransactionsPage(engine, rates, scope, events.publish)
    portfolio_page = PortfolioPage(engine, rates, scope)
    bonds_page = BondsPage(
        engine,
        rates,
        scope,
        on_saved=lambda: events.publish(Change.TRANSACTIONS),
        on_deposits_changed=lambda: events.publish(Change.TERM_DEPOSITS),
    )
    unpriced = UnpricedSection(engine)
    sale_page = SaleSummaryPage(engine, scope, period)
    income_page = PassiveIncomePage(engine, rates, scope)
    benchmarks_page = BenchmarksPage(engine, scope, period, lambda: shared.days, lambda: fetch_in_background())

    # A Successful Refresh is snapshotted once History has been computed after it (issue #115, ADR-0008)
    snapshot_due = False

    async def load_history() -> None:
        """Compute History (or take it already computed) and show it in the switcher; a snapshot due is taken."""
        nonlocal snapshot_due
        await shared.values()
        # Only History computed since the refresh, not the days of a computation it overtook
        if snapshot_due and (days := shared.history.computed):
            snapshot_due = False
            take_snapshot(engine, rates, days, now())
        events.publish(Change.HISTORY)

    def history_outdated() -> None:
        shared.invalidate()
        events.publish(Change.HISTORY)
        background_tasks.create(load_history(), name="history")

    # First, so that a change outdating History has it invalidated before any tab redraws
    events.subscribe(
        history_outdated,
        {Change.TRANSACTIONS, Change.PRICES, Change.BOND_DATA, Change.INSTRUMENTS, Change.TERM_DEPOSITS},
    )

    # A Multi-asset Split changes the value History counts in each Asset Class
    multi_asset_page = MultiAssetPage(engine, rates, scope, on_split_saved=lambda: events.publish(Change.INSTRUMENTS))

    async def fetch_history() -> None:
        # The status follows the fetch's progress, which a worker thread advances
        progress = ui.timer(0.5, history_state.refresh)
        fetch = shared.fetch()
        history_state.refresh()
        try:
            await fetch
        finally:
            progress.cancel()
            history_state.refresh()
        await load_history()

    def fetch_in_background() -> None:
        # A timer in the header, so the fetch's status has the window's slot whichever tab asked for it
        with header:
            ui.timer(0, fetch_history, once=True)

    # Each tab declares the changes it redraws on; only the tab on screen has something to redraw, the others rebuild
    # from the database when opened
    tabs: list[Redrawing] = [
        dashboard_page, strategy_page, results_page, transactions_page, portfolio_page, bonds_page, multi_asset_page,
        unpriced, sale_page, income_page, benchmarks_page,
    ]  # fmt: skip
    for redrawing in tabs:
        events.subscribe(redrawing.refresh, redrawing.CHANGES)

    def transactions_changed() -> None:
        events.publish(Change.TRANSACTIONS)

    def instruments_changed() -> None:
        # A class or Multi-asset Split changed in Ustawienia moves value between the Asset Classes
        events.publish(Change.INSTRUMENTS)

    scope.on_change(lambda: events.publish(Change.SCOPE))

    def account_deleted(account_id: int) -> None:
        # A View Scope on the deleted Account goes back to Total; otherwise only the switcher lists one less
        if scope.account_id == account_id:
            scope.switch(None)
        else:
            switcher.refresh()
        # Its Recurring Rules went with it, so their Drafts are no longer counted
        events.publish(Change.RECURRING_RULES)

    async def refresh_now() -> None:
        nonlocal snapshot_due
        running = _running_refreshes.get(engine)
        if running is None:
            # The sources answer over the network, so the window keeps working meanwhile
            running = asyncio.ensure_future(run.io_bound(_refresh, engine, sources, bond_data, now))
            _running_refreshes[engine] = running
            running.add_done_callback(lambda _: _running_refreshes.pop(engine, None))
        refresh_button.props("loading")
        price_status.refresh()
        try:
            # Shielded, so that closing this window never cancels the refresh another window waits for
            result = await asyncio.shield(running)
        except Exception as error:  # noqa: BLE001 - the window must stay usable whatever the refresh hit
            ui.notify(f"Odświeżanie wycen nie powiodło się: {error}", type="negative")
            return
        finally:
            refresh_button.props(remove="loading")
            price_status.refresh()
        if result is None:  # the app is shutting down
            return
        # A failed refresh saves nothing, not even the snapshot a success before it left due
        snapshot_due = result.succeeded
        # The refresh fetches the bond data due today along with the prices
        events.publish(Change.PRICES, Change.BOND_DATA)
        ui.notify(_refresh_message(result), type="warning" if result.failures else "positive")
        if notice := out_of_band_notice(engine, rates):
            ui.notify(notice, type="warning", multi_line=True)

    async def refresh_bond_data_now(sources: BondDataSources) -> None:
        await run.io_bound(refresh_bond_data, engine, sources, now)
        events.publish(Change.BOND_DATA)

    async def start() -> None:
        if engine in _running_refreshes or (refresh_at_start and refresh_due(last_successful_refresh(engine), now())):
            await refresh_now()
        elif refresh_at_start and bond_data and bond_data_due(bond_data_statuses(engine), now()):
            # Prices are fresh, yet a new day may have brought bond data
            await refresh_bond_data_now(bond_data)
        if refresh_at_start or shared.fetching is not None:
            await fetch_history()

    apply_theme(theme.theme)
    # A new Theme restyles the whole window, its charts drawn on canvas too, so the window is built again in it
    theme.on_change(ui.navigate.reload)

    with ui.header().classes("k-header items-center px-6").props("bordered=false").mark("header") as header:
        ui.space()
        # MF's new rates may value a matured Series, so the bond data refresh redraws it too
        drafts_state = ui.refreshable(lambda: drafts_count(engine, rates.today()))
        drafts_state()
        events.subscribe(
            drafts_state.refresh, {Change.TRANSACTIONS, Change.PRICES, Change.BOND_DATA, Change.TERM_DEPOSITS}
        )
        # The Recurring Rules' Drafts are counted apart from the bonds' (issue #97)
        recurring_state = ui.refreshable(lambda: recurring_drafts_count(engine, rates.today()))
        recurring_state()
        events.subscribe(recurring_state.refresh, {Change.TRANSACTIONS, Change.RECURRING_RULES})
        history_state = ui.refreshable(lambda: history_status(engine, shared))
        history_state()
        bond_state = ui.refreshable(lambda: bond_data_status(engine))
        bond_state()
        events.subscribe(bond_state.refresh, {Change.BOND_DATA})
        price_status = ui.refreshable(lambda: _price_status(engine, engine in _running_refreshes))
        price_status()
        refresh_button = ui.button(icon="refresh", on_click=refresh_now).props(
            'flat round color=ink aria-label="Odśwież wyceny"'
        )
        refresh_button.tooltip("Odśwież wyceny").mark("refresh-prices")
        switcher = ScopeSwitcher(scope, lambda: shared.days)
        events.subscribe(switcher.refresh, switcher.CHANGES)
        other = Theme.LIGHT if theme.theme is Theme.GOLDEN else Theme.GOLDEN
        theme_button = ui.button(
            icon="light_mode" if theme.theme is Theme.GOLDEN else "dark_mode", on_click=lambda: theme.choose(other)
        )
        theme_button.props(f'flat round color=primary aria-label="Motyw: {other.label}"').mark("theme-toggle")
        theme_button.tooltip(f"Motyw: {other.label}")

    # The tab on screen, lit in the menu
    shown_path = {"path": "/"}

    # A tab hidden in Wygląd i widoczność leaves the menu, yet its address still opens it
    @ui.refreshable
    def menu() -> None:
        for tab in TABS:
            if tab.path == SETTINGS_PATH:
                ui.separator().classes("my-3 opacity-20")
            if layout.shows(tab_key(tab.path)):
                button = ui.button(tab.label, icon=tab.icon, on_click=lambda path=tab.path: ui.navigate.to(path))
                lit = tab.path == shown_path["path"]
                button.props(f"flat align=left no-caps no-wrap color={'side-active' if lit else 'side'}")
                button.classes("k-menu-item w-full" + (" k-active" if lit else ""))
        if layout.shows("sayings"):
            menu_saying(now().date())

    # top_corner: the menu runs the window's full height, beside the header rather than under it
    drawer = ui.left_drawer(value=True, top_corner=True).classes("k-side").props("width=260")
    with drawer.mark("nav-menu"):
        with ui.row().classes("items-center gap-3 no-wrap px-2 pt-2 pb-6"):
            ui.image(APP_LOGO).props("no-transition no-spinner").classes("w-10 h-10 shrink-0").mark("app-logo")
            with ui.column().classes("gap-0"):
                ui.label(APP_TITLE).classes("text-xl font-bold tracking-widest text-white")
                ui.label(__version__).classes("text-xs opacity-60")
        menu()
    events.subscribe(menu.refresh, {Change.LAYOUT})

    with ui.page_sticky(position="bottom-right", x_offset=24, y_offset=24):
        add_button = ui.button(
            icon="add", on_click=lambda: open_transaction_dialog(engine, rates, transactions_changed)
        )
        add_button.props('fab color=primary aria-label="Dodaj transakcję"').mark("add-transaction")

    def showing_add_button(path: str, build: Callable[[], None], shown: bool) -> Callable[[], None]:
        """``build`` the tab at ``path``, lit in the menu, with the "+" shown on it or not (L-28: not on Ustawienia
        nor Pomoc)."""

        def build_tab() -> None:
            add_button.visible = shown
            shown_path["path"] = path
            menu.refresh()
            build()

        return build_tab

    @ui.refreshable
    def scope_pages(build: Callable[[], None]) -> None:
        breadcrumbs(scope)
        build()

    events.subscribe(scope_pages.refresh, {Change.SCOPE})

    def placeholder(tab: Tab) -> Callable[[], None]:
        return lambda: scope_pages(_placeholder_page(tab.label))

    pages: dict[str, Callable[[], None]] = {tab.path: placeholder(tab) for tab in TABS}
    pages["/transakcje"] = transactions_page.build
    pages["/portfolio"] = portfolio_page.build
    pages["/"] = lambda: scope_pages(dashboard_page.build)
    pages["/wyniki"] = lambda: scope_pages(results_page.build)
    pages["/multi-asset"] = lambda: scope_pages(multi_asset_page.build)
    pages["/obligacje"] = lambda: scope_pages(bonds_page.build)
    pages["/strategie"] = lambda: scope_pages(strategy_page.build)
    pages["/benchmarki"] = lambda: scope_pages(benchmarks_page.build)
    pages["/sprzedaz"] = lambda: scope_pages(sale_page.build)
    pages["/dochod-pasywny"] = lambda: scope_pages(income_page.build)
    pages[SETTINGS_PATH] = lambda: build_settings_page(
        engine,
        rates,
        search,
        sources,
        unpriced,
        instruments_changed,
        transactions_changed,
        account_deleted,
        lambda: events.publish(Change.RECURRING_RULES),
        layout,
        theme,
    )
    pages[HELP_PATH] = lambda: build_help_page({tab.path: tab.label for tab in TABS})
    pages = {path: showing_add_button(path, build, path not in WITHOUT_ADD_BUTTON) for path, build in pages.items()}
    ui.sub_pages(pages).classes("w-full px-2").mark("page-content")

    # Once the window is up, so that it never waits for the sources or the computation
    ui.timer(0, load_history, once=True)
    ui.timer(0, start, once=True)


def _refresh(
    engine: Engine,
    sources: Mapping[str, PriceSource],
    bond_data: BondDataSources | None,
    now: Callable[[], datetime],
) -> RefreshResult:
    """Refresh the prices, then the bond data due today; a bond data failure never fails the price refresh."""
    result = refresh_prices(engine, sources, now)
    if bond_data is not None:
        refresh_bond_data(engine, bond_data, now)
    return result


def _price_status(engine: Engine, refreshing: bool) -> None:
    """ "Wyceny: <time of the last refresh>", red with the number of errors; clicking lists them with their reasons.
    While a refresh runs it says so."""
    status = last_refresh(engine)
    failures = status.failures if status and not refreshing else []
    text = "Wyceny: odświeżanie…" if refreshing else refresh_summary(status)
    button = ui.button(text, on_click=lambda: _price_errors_dialog(engine)).props("flat no-caps")
    button.props(f"color={'negative' if failures else 'ink'}").mark("price-status")


def _price_errors_dialog(engine: Engine) -> None:
    """The Instruments the last refresh failed for, with each Price Source's reason."""
    status = last_refresh(engine)
    with ui.dialog() as dialog, ui.card().classes("min-w-96").mark("price-errors"):
        ui.label("Wyceny").classes("text-lg font-bold")
        if status is None:
            ui.label("Wyceny nie były jeszcze odświeżane.")
        elif not status.failures:
            ui.label(f"Ostatnie odświeżenie ({format_datetime(status.refreshed_at)}) powiodło się.")
        else:
            ui.label(f"Bez notowania po odświeżeniu {format_datetime(status.refreshed_at)}:")
            for failure in status.failures:
                ui.label(failure.instrument).classes("font-medium")
                for source, reason in failure.reasons.items():
                    ui.label(source_reason(source, reason)).classes("text-sm pl-4")
        with ui.row().classes("w-full justify-end"):
            ui.button("Zamknij", on_click=dialog.close).props("flat")
    dialog.on("hide", dialog.delete)
    dialog.open()


def _refresh_message(result: RefreshResult) -> str:
    """A short summary of a refresh; the header lists the failures with their reasons."""
    message = f"Odświeżono wyceny: {result.refreshed}."
    if result.failures:
        names = ", ".join(failure.instrument for failure in result.failures)
        message += f" Bez notowania: {names}."
    return message


def _placeholder_page(title: str) -> Callable[[], None]:
    def build() -> None:
        ui.label(title).classes("text-2xl font-bold")
        ui.label("Ta zakładka jest w przygotowaniu.").classes("text-gray-500")

    return build
