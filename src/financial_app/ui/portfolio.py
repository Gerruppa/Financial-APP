"""The Portfolio tab: a read-only card per Account (spec section 5). For now: the PLN Cash Balance."""

from dataclasses import dataclass
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_pln
from financial_app.domain.transactions import cash_balances
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.transactions import list_transactions


@dataclass
class PortfolioPage:
    """The Portfolio tab. It never offers editing controls."""

    engine: Engine

    def refresh(self) -> None:
        """Redraw the cards if they are on screen (e.g. after a save)."""
        self.cards.refresh()

    def build(self) -> None:
        ui.label("Portfolio").classes("text-2xl font-bold")
        # The marker sits outside the refreshable cards so it survives a refresh
        with ui.column().classes("w-full max-w-4xl").mark("portfolio"):
            self.cards()

    @ui.refreshable_method
    def cards(self) -> None:
        balances = cash_balances(list_transactions(self.engine))
        # Inactive Accounts stay hidden unless they still hold cash
        accounts = [a for a in list_accounts(self.engine) if a.active or balances.get(a.id, Decimal(0))]
        if not accounts:
            ui.label("Brak kont. Dodaj konto w zakładce Ustawienia.").classes("text-gray-500")
        for account in accounts:
            with ui.card().classes("w-full"):
                with ui.row().classes("w-full items-center"):
                    ui.label(account.name).classes("text-lg font-medium")
                    ui.badge(account.account_type.label).props("outline")
                    ui.space()
                    ui.label("Saldo gotówki").classes("text-gray-500")
                    ui.label(format_pln(balances.get(account.id, Decimal(0)))).classes("text-lg font-medium")
