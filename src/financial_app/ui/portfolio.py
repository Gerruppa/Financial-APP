"""The Portfolio tab: a read-only, expandable card per Account (spec section 5) with its Cash Balance and Positions.

Positions are valued at the Manual Price, converted from a foreign currency at the NBP Rate from the last business
day before today; one without a price or a rate counts at cost and adds nothing to the result. Clicking a Position
shows its Lots with both costs.
"""

from dataclasses import dataclass
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.accounts import Account
from financial_app.domain.currencies import MissingNbpRateError
from financial_app.domain.formatting import format_date, format_percent, format_pln, format_quantity, format_unit_price
from financial_app.domain.instruments import Instrument
from financial_app.domain.lots import Position, open_positions
from financial_app.domain.transactions import cash_balances
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import list_transactions
from financial_app.sources.nbp import NbpRates

COLUMNS = "grid-template-columns: minmax(8rem, 2fr) repeat(7, minmax(6rem, 1fr))"
HEADERS = ("Instrument", "Liczba", "Śr. cena", "Koszt", "Cena", "Wartość", "Zysk/strata", "Zysk/strata %")
LOT_COLUMNS = "grid-template-columns: repeat(4, minmax(6rem, 10rem))"
PLN = "PLN"


@dataclass(frozen=True)
class _Quote:
    """An Instrument's Manual Price in its own currency and in PLN; without ``pln``, ``missing`` says why."""

    price: Decimal | None
    currency: str
    pln: Decimal | None
    missing: str = ""


@dataclass
class PortfolioPage:
    """The Portfolio tab. It never offers editing controls."""

    engine: Engine
    rates: NbpRates

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
        held_instruments = {p.instrument_id for p in positions}
        quotes = self._quotes([i for i in instruments if i.id in held_instruments])
        for account in accounts:
            own = sorted(
                (p for p in positions if p.account_id == account.id),
                key=lambda p: names[p.instrument_id].casefold(),
            )
            _account_card(account, balances.get(account.id, Decimal(0)), own, quotes, names)

    def _quotes(self, instruments: list[Instrument]) -> dict[int, _Quote]:
        """Each Instrument's Manual Price, in PLN at the NBP Rate from the last business day before today."""
        rates: dict[str, Decimal | None] = {PLN: Decimal(1)}
        quotes = {}
        for instrument in instruments:
            price, currency = instrument.manual_price, instrument.quote_currency
            if price is None:
                quotes[instrument.id] = _Quote(None, currency, None, "brak ceny")
                continue
            if currency not in rates:
                try:
                    rates[currency] = self.rates.latest(currency).rate
                except MissingNbpRateError:
                    rates[currency] = None
            rate = rates[currency]
            if rate is None:
                quotes[instrument.id] = _Quote(price, currency, None, "brak kursu")
            else:
                quotes[instrument.id] = _Quote(price, currency, price * rate)
        return quotes


def _account_card(
    account: Account,
    cash: Decimal,
    positions: list[Position],
    quotes: dict[int, _Quote],
    names: dict[int, str],
) -> None:
    value = cash + sum((_value(p, quotes[p.instrument_id].pln) for p in positions), Decimal(0))
    result = sum((_result(p, quotes[p.instrument_id].pln) for p in positions), Decimal(0))
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
            _positions_table(positions, quotes, names)


def _positions_table(positions: list[Position], quotes: dict[int, _Quote], names: dict[int, str]) -> None:
    with ui.element("div").classes("grid w-full gap-x-4 border-b py-1 font-medium").style(COLUMNS):
        for header in HEADERS:
            ui.label(header).classes("text-right" if header != "Instrument" else "")
    for position in positions:
        row = ui.element("div").classes("grid w-full gap-x-4 border-b py-1 cursor-pointer hover:bg-gray-100")
        with row.style(COLUMNS).mark("position-row"):
            ui.label(names[position.instrument_id])
            ui.label(format_quantity(position.quantity)).classes("text-right")
            ui.label(format_pln(position.average_price)).classes("text-right")
            ui.label(format_pln(position.cost)).classes("text-right")
            _valuation_cells(position, quotes[position.instrument_id])
        details = _lots_table(position)
        row.on("click", lambda details=details: details.set_visibility(not details.visible))


def _valuation_cells(position: Position, quote: _Quote) -> None:
    """Price, value and result; without a PLN price, the reason ("brak ceny", "brak kursu") and dashes."""
    if quote.price is None:
        ui.label(quote.missing).classes("text-right text-gray-500")
    else:
        ui.label(format_unit_price(quote.price, quote.currency)).classes("text-right")
    price = quote.pln
    if price is None:
        cells = ["—"] * 3 if quote.price is None else [quote.missing, "—", "—"]
        for cell in cells:
            ui.label(cell).classes("text-right text-gray-500")
        return
    result = position.result(price)
    ui.label(format_pln(position.value(price))).classes("text-right")
    ui.label(format_pln(result, signed=True)).classes(f"text-right {_result_color(result)}")
    ui.label(format_percent(position.result_percent(price), signed=True)).classes(f"text-right {_result_color(result)}")


def _lots_table(position: Position) -> ui.element:
    """The Position's open Lots with their Actual and Tax cost, hidden until the Position is clicked."""
    with ui.column().classes("w-full gap-0 pl-8 pb-2").mark("position-lots") as details:
        with ui.element("div").classes("grid gap-x-4 text-sm font-medium").style(LOT_COLUMNS):
            for header in ("Data zakupu", "Liczba", "Koszt rzeczywisty", "Koszt podatkowy"):
                ui.label(header).classes("text-right" if header != "Data zakupu" else "")
        for lot in position.lots:
            with ui.element("div").classes("grid gap-x-4 text-sm").style(LOT_COLUMNS):
                ui.label(format_date(lot.date))
                ui.label(format_quantity(lot.quantity)).classes("text-right")
                ui.label(format_pln(lot.cost)).classes("text-right")
                ui.label(format_pln(lot.tax_cost)).classes("text-right")
    details.visible = False
    return details


def _value(position: Position, price: Decimal | None) -> Decimal:
    return position.cost if price is None else position.value(price)


def _result(position: Position, price: Decimal | None) -> Decimal:
    return Decimal(0) if price is None else position.result(price)


def _result_color(result: Decimal) -> str:
    return "text-positive" if result > 0 else "text-negative" if result < 0 else ""
