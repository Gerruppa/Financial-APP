"""App shell (UI prototype variant B, issue #1): left menu, header with View Scope, "+" button."""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from nicegui import background_tasks, run, ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_datetime
from financial_app.domain.instrument_search import CombinedSearch, InstrumentSearch
from financial_app.domain.prices import ANALIZY, BANKIER, BOSSA, SOURCE_NAMES, YAHOO, refresh_due, source_reason
from financial_app.persistence.quotes import last_successful_refresh
from financial_app.sources.analizy import AnalizySearch, AnalizySource
from financial_app.sources.bankier import BankierSource
from financial_app.sources.bossa import BossaSource
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates
from financial_app.sources.portfolio_history import PortfolioHistory
from financial_app.sources.prices import PriceSource, RefreshResult, last_refresh, refresh_prices, refresh_summary
from financial_app.sources.yahoo import YahooSearch, YahooSource
from financial_app.ui.dashboard import DashboardPage
from financial_app.ui.dialogs import install_movable_dialogs
from financial_app.ui.history import history_status, shared_history
from financial_app.ui.multi_asset import MultiAssetPage
from financial_app.ui.periods import PeriodChoice
from financial_app.ui.portfolio import PortfolioPage
from financial_app.ui.results import ResultsPage
from financial_app.ui.settings import build_settings_page
from financial_app.ui.transactions import TransactionsPage, open_transaction_dialog
from financial_app.ui.unpriced import UnpricedSection
from financial_app.ui.view_scope import ScopeSwitcher, ViewScope, breadcrumbs

APP_TITLE = "Moje inwestycje"


@dataclass(frozen=True)
class Tab:
    label: str
    path: str
    icon: str


TABS = [
    Tab("Dashboard", "/", "dashboard"),
    Tab("Wyniki", "/wyniki", "insights"),
    Tab("Portfolio", "/portfolio", "account_balance_wallet"),
    Tab("Transakcje", "/transakcje", "receipt_long"),
    Tab("Strategie inwestycyjne", "/strategie", "flag"),
    Tab("Obligacje", "/obligacje", "savings"),
    Tab("Multi-asset", "/multi-asset", "pie_chart"),
    Tab("Benchmarki", "/benchmarki", "compare_arrows"),
    Tab("Ustawienia", "/ustawienia", "settings"),
]

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
) -> None:
    """Build the whole window; tabs are client-side sub-pages backed by the database at ``engine``.

    ``rates`` gives NBP Rates (by default from the NBP API through the cache in that database) and ``sources`` the
    Price Sources by their key (by default the real ones). With ``refresh_at_start`` the prices are refreshed in the
    background once the window is open, when they are due at ``now`` (spec 4.1). ``search`` finds Instruments for
    the Instrument dialog (by default Yahoo and analizy.pl together). ``history`` is the database's History (by
    default fetched from Yahoo and Stooq, computed in the process pool); with ``refresh_at_start`` its missing days are
    fetched after the price refresh.
    """
    rates = rates or NbpRates(engine)
    if sources is None:
        sources = {YAHOO: YahooSource(), BOSSA: BossaSource(), ANALIZY: AnalizySource(), BANKIER: BankierSource()}
    search = search or CombinedSearch({SOURCE_NAMES[YAHOO]: YahooSearch(), SOURCE_NAMES[ANALIZY]: AnalizySearch()})
    install_movable_dialogs()
    shared = shared_history(
        engine, lambda: history or PortfolioHistory(engine, QuoteHistory(engine), rates, lambda: now().date())
    )
    scope = ViewScope(engine)
    period = PeriodChoice(engine, lambda: now().date())
    dashboard_page = DashboardPage(engine, rates, scope, period, lambda: shared.days)
    results_page = ResultsPage(engine, scope, period, lambda: shared.days)
    transactions_page = TransactionsPage(engine, rates, scope)
    portfolio_page = PortfolioPage(engine, rates, scope)
    unpriced = UnpricedSection(engine)
    # A Multi-asset Split changes the value History counts in each Asset Class
    multi_asset_page = MultiAssetPage(engine, rates, scope, on_split_saved=lambda: history_outdated())

    async def load_history() -> None:
        """Compute History (or take it already computed) and show it in the switcher."""
        await shared.values()
        switcher.refresh()
        dashboard_page.refresh()
        results_page.refresh()

    def history_outdated() -> None:
        shared.invalidate()
        switcher.refresh()
        dashboard_page.refresh()
        results_page.refresh()
        background_tasks.create(load_history(), name="history")

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

    def transactions_changed() -> None:
        # Only the tab on screen has something to redraw; the others rebuild from the database when opened
        transactions_page.refresh()
        portfolio_page.refresh()
        multi_asset_page.refresh()
        unpriced.refresh()
        history_outdated()

    def instruments_changed() -> None:
        # A class or Multi-asset Split changed in Ustawienia moves value between the Asset Classes
        unpriced.refresh()
        history_outdated()

    def scope_changed() -> None:
        switcher.refresh()
        transactions_page.refresh()
        portfolio_page.refresh()
        multi_asset_page.refresh()
        dashboard_page.refresh()
        results_page.refresh()
        scope_pages.refresh()

    scope.on_change(scope_changed)

    async def refresh_now() -> None:
        running = _running_refreshes.get(engine)
        if running is None:
            # The sources answer over the network, so the window keeps working meanwhile
            running = asyncio.ensure_future(run.io_bound(refresh_prices, engine, sources, now))
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
        portfolio_page.refresh()
        multi_asset_page.refresh()
        unpriced.refresh()
        history_outdated()
        ui.notify(_refresh_message(result), type="warning" if result.failures else "positive")

    async def start() -> None:
        if engine in _running_refreshes or (refresh_at_start and refresh_due(last_successful_refresh(engine), now())):
            await refresh_now()
        if refresh_at_start or shared.fetching is not None:
            await fetch_history()

    with ui.header().classes("bg-indigo-900 items-center").mark("header"):
        ui.label(APP_TITLE).classes("text-lg font-bold")
        ui.space()
        history_state = ui.refreshable(lambda: history_status(engine, shared))
        history_state()
        price_status = ui.refreshable(lambda: _price_status(engine, engine in _running_refreshes))
        price_status()
        refresh_button = ui.button(icon="refresh", on_click=refresh_now).props(
            'flat round color=white aria-label="Odśwież wyceny"'
        )
        refresh_button.tooltip("Odśwież wyceny").mark("refresh-prices")
        switcher = ScopeSwitcher(scope, lambda: shared.days)

    with ui.left_drawer(value=True).classes("bg-indigo-950").props("width=260").mark("nav-menu"):
        for tab in TABS:
            ui.button(tab.label, icon=tab.icon, on_click=lambda path=tab.path: ui.navigate.to(path)).props(
                "flat align=left no-caps no-wrap color=white"
            ).classes("w-full")

    with ui.page_sticky(position="bottom-right", x_offset=24, y_offset=24):
        ui.button(icon="add", on_click=lambda: open_transaction_dialog(engine, rates, transactions_changed)).props(
            'fab color=indigo aria-label="Dodaj transakcję"'
        ).mark("add-transaction")

    @ui.refreshable
    def scope_pages(build: Callable[[], None]) -> None:
        breadcrumbs(scope)
        build()

    def placeholder(tab: Tab) -> Callable[[], None]:
        return lambda: scope_pages(_placeholder_page(tab.label))

    pages: dict[str, Callable[[], None]] = {tab.path: placeholder(tab) for tab in TABS}
    pages["/transakcje"] = transactions_page.build
    pages["/portfolio"] = portfolio_page.build
    pages["/"] = lambda: scope_pages(dashboard_page.build)
    pages["/wyniki"] = lambda: scope_pages(results_page.build)
    pages["/multi-asset"] = lambda: scope_pages(multi_asset_page.build)
    pages["/ustawienia"] = lambda: build_settings_page(engine, rates, search, sources, unpriced, instruments_changed)
    ui.sub_pages(pages).classes("w-full").mark("page-content")

    # Once the window is up, so that it never waits for the sources or the computation
    ui.timer(0, load_history, once=True)
    ui.timer(0, start, once=True)


def _price_status(engine: Engine, refreshing: bool) -> None:
    """ "Wyceny: <time of the last refresh>", red with the number of errors; clicking lists them with their reasons.
    While a refresh runs it says so."""
    status = last_refresh(engine)
    failures = status.failures if status and not refreshing else []
    text = "Wyceny: odświeżanie…" if refreshing else refresh_summary(status)
    button = ui.button(text, on_click=lambda: _price_errors_dialog(engine)).props("flat no-caps")
    button.props(f"color={'red-4' if failures else 'white'}").mark("price-status")


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
