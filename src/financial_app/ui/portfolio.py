"""The Portfolio tab: a read-only, expandable card per Account (spec section 5) with its Cash Balances and Positions.

Positions are valued at the Manual Price, converted from a foreign currency at the NBP Rate from the last business
day before today; one without a price or a rate counts at cost and adds nothing to the result. Clicking a Position
shows its Lots with both costs. Foreign cash is valued at the same NBP Rate; its FX result (realised and unrealised)
counts in the Account's result unless the Account excludes it (spec 3.1, 3.5). Each card also sums the Account's
net Dividends and interest and its commissions and costs.
"""

from dataclasses import dataclass
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.accounts import Account
from financial_app.domain.currencies import MissingNbpRateError
from financial_app.domain.formatting import (
    format_amount,
    format_date,
    format_percent,
    format_pln,
    format_quantity,
    format_rate,
    format_unit_price,
)
from financial_app.domain.instruments import Instrument
from financial_app.domain.lots import ForeignCash, Position, foreign_cash, fx_result, open_positions
from financial_app.domain.transactions import PLN, cash_balances, costs_by_account, dividends_by_account
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import list_transactions
from financial_app.sources.nbp import NbpRates

COLUMNS = "grid-template-columns: minmax(8rem, 2fr) repeat(7, minmax(6rem, 1fr))"
HEADERS = ("Instrument", "Liczba", "Śr. cena", "Koszt", "Cena", "Wartość", "Zysk/strata", "Zysk/strata %")
LOT_COLUMNS = "grid-template-columns: repeat(4, minmax(6rem, 10rem))"
CASH_COLUMNS = "grid-template-columns: repeat(5, minmax(6rem, 10rem))"


@dataclass(frozen=True)
class _Quote:
    """An Instrument's Manual Price in its own currency and in PLN; without ``pln``, ``missing`` says why."""

    price: Decimal | None
    currency: str
    pln: Decimal | None
    missing: str = ""


@dataclass(frozen=True)
class _Totals:
    """Net Dividends and interest, and commissions and costs, in PLN per Account id."""

    dividends: dict[int, Decimal]
    costs: dict[int, Decimal]


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
        cash = foreign_cash(reversed(transactions))
        balances = cash_balances(transactions)
        totals = _Totals(dividends_by_account(transactions), costs_by_account(transactions))
        held = {position.account_id for position in positions} | {c.account_id for c in cash if c.lots}
        # Inactive Accounts stay hidden unless they still hold cash or Positions
        accounts = [a for a in list_accounts(self.engine) if a.active or balances.get(a.id, Decimal(0)) or a.id in held]
        if not accounts:
            ui.label("Brak kont. Dodaj konto w zakładce Ustawienia.").classes("text-gray-500")
        instruments = list_instruments(self.engine)
        names = {i.id: i.name for i in instruments}
        held_instruments = {p.instrument_id for p in positions}
        rates: dict[str, Decimal | None] = {PLN: Decimal(1)}
        quotes = self._quotes([i for i in instruments if i.id in held_instruments], rates)
        for balance in cash:
            self._rate(balance.currency, rates)
        for account in accounts:
            own = sorted(
                (p for p in positions if p.account_id == account.id),
                key=lambda p: names[p.instrument_id].casefold(),
            )
            own_cash = sorted((c for c in cash if c.account_id == account.id), key=lambda c: c.currency)
            _account_card(account, balances.get(account.id, Decimal(0)), own, own_cash, quotes, rates, names, totals)

    def _rate(self, currency: str, rates: dict[str, Decimal | None]) -> Decimal | None:
        """The NBP Rate from the last business day before today, fetched once per currency into ``rates``."""
        if currency not in rates:
            try:
                rates[currency] = self.rates.latest(currency).rate
            except MissingNbpRateError:
                rates[currency] = None
        return rates[currency]

    def _quotes(self, instruments: list[Instrument], rates: dict[str, Decimal | None]) -> dict[int, _Quote]:
        """Each Instrument's Manual Price, in PLN at the NBP Rate from the last business day before today."""
        quotes = {}
        for instrument in instruments:
            price, currency = instrument.manual_price, instrument.quote_currency
            if price is None:
                quotes[instrument.id] = _Quote(None, currency, None, "brak ceny")
                continue
            rate = self._rate(currency, rates)
            if rate is None:
                quotes[instrument.id] = _Quote(price, currency, None, "brak kursu")
            else:
                quotes[instrument.id] = _Quote(price, currency, price * rate)
        return quotes


def _account_card(
    account: Account,
    cash: Decimal,
    positions: list[Position],
    foreign: list[ForeignCash],
    quotes: dict[int, _Quote],
    rates: dict[str, Decimal | None],
    names: dict[int, str],
    totals: _Totals,
) -> None:
    known_rates = {currency: rate for currency, rate in rates.items() if rate is not None}
    value = (
        cash
        + sum((_value(p, quotes[p.instrument_id].pln) for p in positions), Decimal(0))
        + sum((_cash_value(c, known_rates.get(c.currency)) for c in foreign), Decimal(0))
    )
    fx = fx_result(foreign, account.id, known_rates)
    result = sum((_result(p, quotes[p.instrument_id].pln) for p in positions), Decimal(0))
    if not account.exclude_fx_result:
        result += fx
    with ui.card().classes("w-full p-0"), ui.expansion(value=True).classes("w-full") as card:
        with card.add_slot("header"), ui.row().classes("w-full items-center"):
            ui.label(account.name).classes("text-lg font-medium")
            ui.badge(account.account_type.label).props("outline")
            ui.space()
            if positions or foreign:
                result_label = ui.label(format_pln(result, signed=True)).classes(_result_color(result))
                result_label.mark("account-result")
            ui.label(format_pln(value)).classes("text-lg font-medium")
        with ui.row().classes("w-full items-center"):
            ui.label("Saldo gotówki").classes("text-gray-500")
            ui.label(format_pln(cash)).classes("font-medium")
        for title, amounts, marker in (
            ("Dywidendy i odsetki", totals.dividends, "account-dividends"),
            ("Prowizje i koszty", totals.costs, "account-costs"),
        ):
            if account.id in amounts:
                with ui.row().classes("w-full items-center").mark(marker):
                    ui.label(title).classes("text-gray-500")
                    ui.label(format_pln(amounts[account.id])).classes("font-medium")
        if foreign:
            _foreign_cash_table(foreign, known_rates)
            with ui.row().classes("w-full items-center"):
                ui.label("Wynik walutowy").classes("text-gray-500")
                excluded = " (wyłączony z wyniku konta)" if account.exclude_fx_result else ""
                fx_label = ui.label(f"{format_pln(fx, signed=True)}{excluded}").classes(_result_color(fx))
                fx_label.mark("fx-result")
        if positions:
            _positions_table(positions, quotes, names)


def _foreign_cash_table(foreign: list[ForeignCash], rates: dict[str, Decimal]) -> None:
    """Each foreign Cash Balance with its PLN cost and, at the NBP Rate, its value and unrealised FX result."""
    with ui.column().classes("w-full gap-0").mark("foreign-cash"):
        with ui.element("div").classes("grid gap-x-4 text-sm font-medium").style(CASH_COLUMNS):
            for header in ("Gotówka", "Koszt", "Kurs NBP", "Wartość", "Wynik"):
                ui.label(header).classes("text-right" if header != "Gotówka" else "")
        for balance in foreign:
            rate = rates.get(balance.currency)
            with ui.element("div").classes("grid gap-x-4 text-sm").style(CASH_COLUMNS):
                ui.label(format_amount(balance.quantity, balance.currency))
                ui.label(format_pln(balance.cost)).classes("text-right")
                if rate is None:
                    for cell in ("brak kursu", "\u2014", "\u2014"):
                        ui.label(cell).classes("text-right text-gray-500")
                    continue
                result = balance.result(rate)
                ui.label(format_rate(rate)).classes("text-right")
                ui.label(format_pln(balance.value(rate))).classes("text-right")
                ui.label(format_pln(result, signed=True)).classes(f"text-right {_result_color(result)}")


def _cash_value(balance: ForeignCash, rate: Decimal | None) -> Decimal:
    """Foreign cash in PLN at ``rate``; without one, at its cost."""
    return balance.cost if rate is None else balance.value(rate)


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
