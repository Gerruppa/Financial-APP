"""App shell (UI prototype variant B, issue #1): left menu, header with View Scope, "+" button."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from nicegui import run, ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_count, format_datetime
from financial_app.domain.prices import ANALIZY, BANKIER, BOSSA, SOURCE_NAMES, YAHOO
from financial_app.sources.analizy import AnalizySource
from financial_app.sources.bankier import BankierSource
from financial_app.sources.bossa import BossaSource
from financial_app.sources.nbp import NbpRates
from financial_app.sources.prices import PriceSource, RefreshResult, last_refresh, refresh_prices
from financial_app.sources.yahoo import YahooSource
from financial_app.ui.dialogs import install_movable_dialogs
from financial_app.ui.portfolio import PortfolioPage
from financial_app.ui.settings import build_settings_page
from financial_app.ui.transactions import TransactionsPage, open_transaction_dialog

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
    Tab("Benchmarki", "/benchmarki", "compare_arrows"),
    Tab("Ustawienia", "/ustawienia", "settings"),
]

# Only Total for now; Accounts join the switcher in Stage 4 (spec section 5, View Scope)
VIEW_SCOPES = ["Total"]


def build_shell(
    engine: Engine, rates: NbpRates | None = None, sources: Mapping[str, PriceSource] | None = None
) -> None:
    """Build the whole window; tabs are client-side sub-pages backed by the database at ``engine``.

    ``rates`` gives NBP Rates (by default from the NBP API through the cache in that database) and ``sources`` the
    Price Sources by their key (by default the real ones).
    """
    rates = rates or NbpRates(engine)
    if sources is None:
        sources = {YAHOO: YahooSource(), BOSSA: BossaSource(), ANALIZY: AnalizySource(), BANKIER: BankierSource()}
    install_movable_dialogs()
    transactions_page = TransactionsPage(engine, rates)
    portfolio_page = PortfolioPage(engine, rates)

    def transactions_changed() -> None:
        # Only the tab on screen has something to redraw; the others rebuild from the database when opened
        transactions_page.refresh()
        portfolio_page.refresh()

    async def refresh_now() -> None:
        # The sources answer over the network, so the window keeps working meanwhile
        refresh_button.props("loading")
        try:
            result = await run.io_bound(refresh_prices, engine, sources)
        finally:
            refresh_button.props(remove="loading")
        if result is None:  # the app is shutting down
            return
        portfolio_page.refresh()
        price_status.refresh()
        ui.notify(_refresh_message(result), type="warning" if result.failures else "positive")

    with ui.header().classes("bg-indigo-900 items-center").mark("header"):
        ui.label(APP_TITLE).classes("text-lg font-bold")
        ui.space()
        price_status = ui.refreshable(lambda: _price_status(engine))
        price_status()
        refresh_button = ui.button(icon="refresh", on_click=refresh_now).props(
            'flat round color=white aria-label="Odśwież wyceny"'
        )
        refresh_button.tooltip("Odśwież wyceny").mark("refresh-prices")
        ui.select(VIEW_SCOPES, value=VIEW_SCOPES[0], label="Widok").props("dense dark standout").classes("w-48")

    with ui.left_drawer(value=True).classes("bg-indigo-950").props("width=260").mark("nav-menu"):
        for tab in TABS:
            ui.button(tab.label, icon=tab.icon, on_click=lambda path=tab.path: ui.navigate.to(path)).props(
                "flat align=left no-caps no-wrap color=white"
            ).classes("w-full")

    with ui.page_sticky(position="bottom-right", x_offset=24, y_offset=24):
        ui.button(icon="add", on_click=lambda: open_transaction_dialog(engine, rates, transactions_changed)).props(
            'fab color=indigo aria-label="Dodaj transakcję"'
        ).mark("add-transaction")

    pages: dict[str, Callable[[], None]] = {tab.path: _placeholder_page(tab.label) for tab in TABS}
    pages["/transakcje"] = transactions_page.build
    pages["/portfolio"] = portfolio_page.build
    pages["/ustawienia"] = lambda: build_settings_page(engine, rates)
    ui.sub_pages(pages).classes("w-full").mark("page-content")


def _price_status(engine: Engine) -> None:
    """ "Wyceny: <time of the last refresh>", red with the number of errors; clicking lists them with their reasons."""
    status = last_refresh(engine)
    text = f"Wyceny: {format_datetime(status.refreshed_at) if status else 'brak'}"
    if status and status.failures:
        text += f" · {format_count(len(status.failures), 'błąd', 'błędy', 'błędów')}"
    button = ui.button(text, on_click=lambda: _price_errors_dialog(engine)).props("flat no-caps")
    button.props(f"color={'red-4' if status and status.failures else 'white'}").mark("price-status")


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
                    ui.label(f"{SOURCE_NAMES.get(source, source)}: {reason}").classes("text-sm pl-4")
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
