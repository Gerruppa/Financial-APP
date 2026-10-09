"""The Portfolio tab: a read-only, expandable card per Account (spec section 5) with its Cash Balance and Positions.

Positions are valued at the Manual Price; one without a price counts at cost and adds nothing to the result.
"""

from dataclasses import dataclass
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.accounts import Account
from financial_app.domain.formatting import format_percent, format_pln, format_quantity, format_unit_price
from financial_app.domain.lots import Position, open_positions
from financial_app.domain.transactions import cash_balances
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import list_transactions

COLUMNS = "grid-template-columns: minmax(8rem, 2fr) repeat(7, minmax(6rem, 1fr))"
HEADERS = ("Instrument", "Liczba", "Śr. cena", "Koszt", "Cena", "Wartość", "Zysk/strata", "Zysk/strata %")


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
        with ui.column().classes("w-full max-w-6xl").mark("portfolio"):
            self.cards()

    @ui.refreshable_method
    def cards(self) -> None:
        transactions = list_transactions(self.engine)
        # list_transactions is newest first; the FIFO engine wants entry order
        positions = open_positions(reversed(transactions))
        balances = cash_balances(transactions)
        held = {position.account_id for position in positions}
        # Inactive Accounts stay hidden unless they still hold cash or Positions
        accounts = [a for a in list_accounts(self.engine) if a.active or balances.get(a.id, Decimal(0)) or a.id in held]
        if not accounts:
            ui.label("Brak kont. Dodaj konto w zakładce Ustawienia.").classes("text-gray-500")
        instruments = list_instruments(self.engine)
        names = {i.id: i.name for i in instruments}
        prices = {i.id: i.manual_price for i in instruments}
        for account in accounts:
            own = sorted(
                (p for p in positions if p.account_id == account.id),
                key=lambda p: names[p.instrument_id].casefold(),
            )
            _account_card(account, balances.get(account.id, Decimal(0)), own, prices, names)


def _account_card(
    account: Account,
    cash: Decimal,
    positions: list[Position],
    prices: dict[int, Decimal | None],
    names: dict[int, str],
) -> None:
    value = cash + sum((_value(p, prices[p.instrument_id]) for p in positions), Decimal(0))
    result = sum((_result(p, prices[p.instrument_id]) for p in positions), Decimal(0))
    with ui.card().classes("w-full p-0"), ui.expansion(value=True).classes("w-full") as card:
        with card.add_slot("header"), ui.row().classes("w-full items-center"):
            ui.label(account.name).classes("text-lg font-medium")
            ui.badge(account.account_type.label).props("outline")
            ui.space()
            if positions:
                ui.label(format_pln(result, signed=True)).classes(_result_color(result))
            ui.label(format_pln(value)).classes("text-lg font-medium")
        with ui.row().classes("w-full items-center"):
            ui.label("Saldo gotówki").classes("text-gray-500")
            ui.label(format_pln(cash)).classes("font-medium")
        if positions:
            _positions_table(positions, prices, names)


def _positions_table(positions: list[Position], prices: dict[int, Decimal | None], names: dict[int, str]) -> None:
    with ui.element("div").classes("grid w-full gap-x-4 border-b py-1 font-medium").style(COLUMNS):
        for header in HEADERS:
            ui.label(header).classes("text-right" if header != "Instrument" else "")
    for position in positions:
        price = prices[position.instrument_id]
        with ui.element("div").classes("grid w-full gap-x-4 border-b py-1").style(COLUMNS):
            ui.label(names[position.instrument_id])
            ui.label(format_quantity(position.quantity)).classes("text-right")
            ui.label(format_pln(position.average_price)).classes("text-right")
            ui.label(format_pln(position.cost)).classes("text-right")
            if price is None:
                ui.label("brak ceny").classes("text-right text-gray-500")
                for _ in range(3):
                    ui.label("—").classes("text-right text-gray-500")
                continue
            result = position.result(price)
            ui.label(format_unit_price(price)).classes("text-right")
            ui.label(format_pln(position.value(price))).classes("text-right")
            ui.label(format_pln(result, signed=True)).classes(f"text-right {_result_color(result)}")
            ui.label(format_percent(position.result_percent(price), signed=True)).classes(
                f"text-right {_result_color(result)}"
            )


def _value(position: Position, price: Decimal | None) -> Decimal:
    return position.cost if price is None else position.value(price)


def _result(position: Position, price: Decimal | None) -> Decimal:
    return Decimal(0) if price is None else position.result(price)


def _result_color(result: Decimal) -> str:
    return "text-positive" if result > 0 else "text-negative" if result < 0 else ""
