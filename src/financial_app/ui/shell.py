"""App shell (UI prototype variant B, issue #1): left menu, header with View Scope, "+" button."""

from collections.abc import Callable
from dataclasses import dataclass

from nicegui import ui

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

# Only Total for now; Accounts join the switcher once they exist (spec section 5, View Scope)
VIEW_SCOPES = ["Total"]


def build_shell() -> None:
    """Build the whole window; tabs are client-side sub-pages."""
    with ui.header().classes("bg-indigo-900 items-center").mark("header"):
        ui.label(APP_TITLE).classes("text-lg font-bold")
        ui.space()
        ui.select(VIEW_SCOPES, value=VIEW_SCOPES[0], label="Widok").props("dense dark standout").classes("w-48")

    with ui.left_drawer(value=True).classes("bg-indigo-950").props("width=260").mark("nav-menu"):
        for tab in TABS:
            ui.button(tab.label, icon=tab.icon, on_click=lambda path=tab.path: ui.navigate.to(path)).props(
                "flat align=left no-caps no-wrap color=white"
            ).classes("w-full")

    with ui.page_sticky(position="bottom-right", x_offset=24, y_offset=24):
        ui.button(icon="add", on_click=open_transaction_dialog).props(
            'fab color=indigo aria-label="Dodaj transakcję"'
        ).mark("add-transaction")

    ui.sub_pages({tab.path: _placeholder_page(tab.label) for tab in TABS}).classes("w-full").mark("page-content")


def _placeholder_page(title: str) -> Callable[[], None]:
    def build() -> None:
        ui.label(title).classes("text-2xl font-bold")
        ui.label("Ta zakładka jest w przygotowaniu.").classes("text-gray-500")

    return build


def open_transaction_dialog() -> None:
    """Open a fresh transaction dialog; it is built on demand and removed when closed."""
    dialog = ui.dialog()
    dialog.on("hide", dialog.delete)
    with dialog, ui.card().classes("w-[460px]"):
        ui.label("Nowa transakcja").classes("text-lg font-bold")
        ui.label("Formularze transakcji pojawią się w kolejnych etapach.").classes("text-gray-500")
        with ui.row().classes("w-full justify-end"):
            ui.button("Zamknij", on_click=dialog.close).props("flat")
    dialog.open()
