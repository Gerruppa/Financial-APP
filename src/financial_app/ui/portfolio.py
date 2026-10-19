"""The Portfolio tab: a read-only, expandable card per Account (spec section 5) with its Cash Balances and Positions.

Positions are valued at their price from ``domain.valuation`` (the Manual Price or the newest Quote, with a badge when
it is manual, stale, has no source or waits for Stage 3; a physical metal at its spot less the Buyback Spread, with the
spot beside it; a Bond Series by the MF issue letters, each Lot from its purchase day, with the year's rate and its
label when MF has not published it), converted from a foreign currency at the NBP Rate from the last business day before
today; one without a price or a rate counts at cost and adds nothing to the result. Clicking a Position shows its Lots
with both costs, below the fund's TER, Distribution Policy and domicile when entered. Foreign cash is valued at the same
NBP Rate; its FX result (realised and unrealised) counts in the Account's result unless the Account excludes it (spec
3.1, 3.5). Each card also sums the Account's net Dividends and interest and its commissions and costs. In an Account's
View Scope only its card shows, under the breadcrumbs back to Total.
"""

from dataclasses import dataclass
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.account_value import AccountValue, is_listed
from financial_app.domain.accounts import Account
from financial_app.domain.bond_valuation import BondPrice, most_uncertain, rate_text
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
from financial_app.domain.lots import ForeignCash, Lot, Position
from financial_app.domain.prices import SOURCE_NAMES
from financial_app.domain.transactions import costs_by_account, dividends_by_account
from financial_app.domain.valuation import Badge, InstrumentPrice, PriceStatus
from financial_app.sources.nbp import NbpRates
from financial_app.sources.todays_view import TodaysView, todays_view
from financial_app.ui.changes import TODAYS_VALUE
from financial_app.ui.fund_details import fund_details
from financial_app.ui.view_scope import ViewScope, breadcrumbs

COLUMNS = "grid-template-columns: minmax(8rem, 2fr) repeat(7, minmax(6rem, 1fr))"
HEADERS = ("Instrument", "Liczba", "Śr. cena", "Koszt", "Cena", "Wartość", "Zysk/strata", "Zysk/strata %")
LOT_COLUMNS = "grid-template-columns: repeat(4, minmax(6rem, 10rem))"
BOND_LOT_COLUMNS = "grid-template-columns: repeat(6, minmax(6rem, 10rem))"
CASH_COLUMNS = "grid-template-columns: repeat(5, minmax(6rem, 10rem))"
# Why an Instrument has no PLN price
MISSING = {PriceStatus.NO_PRICE: "brak ceny", PriceStatus.NO_RATE: "brak kursu"}


@dataclass(frozen=True)
class _Totals:
    """Net Dividends and interest, and commissions and costs, in PLN per Account id."""

    dividends: dict[int, Decimal]
    costs: dict[int, Decimal]


@dataclass
class PortfolioPage:
    """The Portfolio tab. It never offers editing controls."""

    # The changes it redraws on (ui/changes.py)
    CHANGES = TODAYS_VALUE

    engine: Engine
    rates: NbpRates
    scope: ViewScope

    def refresh(self) -> None:
        """Redraw the cards if they are on screen (e.g. after a save or a scope change)."""
        self.cards.refresh()

    def build(self) -> None:
        ui.label("Portfolio").classes("text-2xl font-bold")
        # The marker sits outside the refreshable cards so it survives a refresh
        with ui.column().classes("w-full").mark("portfolio"):
            self.cards()

    @ui.refreshable_method
    def cards(self) -> None:
        breadcrumbs(self.scope)
        view = todays_view(self.engine, self.rates)
        totals = _Totals(dividends_by_account(view.transactions), costs_by_account(view.transactions))
        values = {account.id: view.account_value(account) for account in view.accounts}
        if self.scope.account_id is None:
            accounts = [a for a in view.accounts if is_listed(a, values[a.id])]
        else:
            accounts = [a for a in view.accounts if a.id == self.scope.account_id]
        if not accounts:
            ui.label("Brak kont. Dodaj konto w zakładce Ustawienia.").classes("text-gray-500")
        for account in accounts:
            own = sorted(
                (p for p in view.positions if p.account_id == account.id),
                key=lambda p: view.instruments[p.instrument_id].name.casefold(),
            )
            own_cash = sorted((c for c in view.foreign if c.account_id == account.id), key=lambda c: c.currency)
            _account_card(account, values[account.id], own, own_cash, view, totals)


def _account_card(
    account: Account,
    value: AccountValue,
    positions: list[Position],
    foreign: list[ForeignCash],
    view: TodaysView,
    totals: _Totals,
) -> None:
    with ui.card().classes("w-full p-0"), ui.expansion(value=True).classes("w-full") as card:
        with card.add_slot("header"), ui.row().classes("w-full items-center"):
            ui.label(account.name).classes("text-lg font-medium")
            ui.badge(account.account_type.label).props("outline")
            ui.space()
            if positions or foreign:
                result = value.result
                result_label = ui.label(format_pln(result, signed=True)).classes(_result_color(result))
                result_label.mark("account-result")
            ui.label(format_pln(value.value)).classes("text-lg font-medium")
        with ui.row().classes("w-full items-center"):
            ui.label("Saldo gotówki").classes("text-gray-500")
            ui.label(format_pln(value.cash)).classes("font-medium")
        if value.accrued:
            # Counted in the value: the Term Deposits' interest not paid into the cash yet, net of Belka (#160)
            with ui.row().classes("w-full items-center").mark("account-accrued"):
                ui.label("Narosłe odsetki lokat").classes("text-gray-500")
                ui.label(format_pln(value.accrued)).classes("font-medium")
        for title, amounts, marker in (
            ("Dywidendy i odsetki", totals.dividends, "account-dividends"),
            ("Prowizje i koszty", totals.costs, "account-costs"),
        ):
            if account.id in amounts:
                with ui.row().classes("w-full items-center").mark(marker):
                    ui.label(title).classes("text-gray-500")
                    ui.label(format_pln(amounts[account.id])).classes("font-medium")
        if foreign:
            _foreign_cash_table(foreign, view.rates)
            with ui.row().classes("w-full items-center"):
                ui.label("Wynik walutowy").classes("text-gray-500")
                excluded = " (wyłączony z wyniku konta)" if account.exclude_fx_result else ""
                fx_label = ui.label(f"{format_pln(value.fx, signed=True)}{excluded}").classes(_result_color(value.fx))
                fx_label.mark("fx-result")
        if positions:
            _positions_table(positions, view.prices, view.instruments)


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


def _positions_table(
    positions: list[Position], prices: dict[int, InstrumentPrice], instruments_by_id: dict[int, Instrument]
) -> None:
    with ui.element("div").classes("grid w-full gap-x-4 border-b py-1 font-medium").style(COLUMNS):
        for header in HEADERS:
            ui.label(header).classes("text-right" if header != "Instrument" else "")
    for position in positions:
        row = ui.element("div").classes("grid w-full gap-x-4 border-b py-1 cursor-pointer hover:bg-gray-100")
        with row.style(COLUMNS).mark("position-row"):
            current = prices[position.instrument_id]
            with ui.row().classes("items-center gap-2"):
                ui.label(instruments_by_id[position.instrument_id].name)
                if current.badge is not None:
                    color = "orange" if current.badge is Badge.STALE else "grey"
                    ui.badge(current.badge.value, color=color).props("outline").mark("price-badge")
            ui.label(format_quantity(position.quantity)).classes("text-right")
            ui.label(format_pln(position.average_price)).classes("text-right")
            ui.label(format_pln(position.cost)).classes("text-right")
            _valuation_cells(position, current)
        details = _lots_table(position, instruments_by_id[position.instrument_id], current.bond)
        row.on("click", lambda details=details: details.set_visibility(not details.visible))


def _valuation_cells(position: Position, current: InstrumentPrice) -> None:
    """Price, value and result; without a PLN price, the reason ("brak ceny", "brak kursu") and dashes."""
    missing = MISSING.get(current.status, "")
    if current.bond is not None:
        _bond_price_cell(position, current.bond)
    elif current.price is None:
        ui.label(missing).classes("text-right text-gray-500")
    else:
        _price_cell(current.price, current)
    price = current.pln
    if price is None:
        cells = ["—"] * 3 if current.price is None else [missing, "—", "—"]
        for cell in cells:
            ui.label(cell).classes("text-right text-gray-500")
        return
    result = position.result(price)
    with ui.column().classes("gap-0 items-end"):
        ui.label(format_pln(position.value(price)))
        if current.unit_spot_pln is not None:
            ui.label(f"spot {format_pln(position.value(current.unit_spot_pln))}").classes("text-xs text-gray-500")
    ui.label(format_pln(result, signed=True)).classes(f"text-right {_result_color(result)}")
    ui.label(format_percent(position.result_percent(price), signed=True)).classes(f"text-right {_result_color(result)}")


def _price_cell(price: Decimal, current: InstrumentPrice) -> None:
    """The price with the day of its Quote; beside a Manual Price, the newest Quote it overrides. A physical metal's
    unit price is rounded to the cent, with the spot of a troy ounce it comes from."""
    ounce = "" if current.spot is None else "/oz"
    with ui.column().classes("gap-0 items-end"):
        if current.spot is None:
            ui.label(format_unit_price(price, current.currency))
        else:
            ui.label(format_amount(price, current.currency))
            ui.label(f"spot {format_unit_price(current.spot, current.currency)}{ounce}").classes(
                "text-xs text-gray-500"
            )
        quote = current.quote
        if quote is None:
            return
        if current.status is PriceStatus.MANUAL:
            source = SOURCE_NAMES.get(quote.source, quote.source)
            caption = f"{source}: {format_unit_price(quote.price, quote.currency)}{ounce} ({format_date(quote.day)})"
        else:
            caption = format_date(quote.day)
        ui.label(caption).classes("text-xs text-gray-500")


def _bond_price_cell(position: Position, bond: BondPrice) -> None:
    """A Bond Series' value of one bond, averaged over its Lots, with the rate of the oldest Lot's year and the most
    uncertain label of any Lot's value."""
    with ui.column().classes("gap-0 items-end"):
        ui.label(format_pln(position.value(bond) / position.quantity))
        _bond_rate(bond, position.lots[0], position.lots)


def _bond_rate(bond: BondPrice, lot: Lot, labelled: tuple[Lot, ...]) -> None:
    """The rate of the year ``lot`` is in, labelled when MF has not published a rate the value of any ``labelled``
    Lot rests on."""
    value = bond.value(lot.date)
    if value is None:
        ui.label("po koszcie").classes("text-xs text-gray-500")
        return
    ui.label(rate_text(value)).classes("text-xs text-gray-500")
    label = most_uncertain(v.label for other in labelled if (v := bond.value(other.date)) is not None)
    if label is not None:
        ui.label(label.value).classes("text-xs text-orange-700").mark("bond-rate-label")


def _lots_table(position: Position, instrument: Instrument, bond: BondPrice | None) -> ui.element:
    """The Position's open Lots with their Actual and Tax cost (a Bond Series' also with each one's rate and value),
    below the fund's details when entered, hidden until the Position is clicked."""
    columns = LOT_COLUMNS if bond is None else BOND_LOT_COLUMNS
    headers = ("Data zakupu", "Liczba", "Koszt rzeczywisty", "Koszt podatkowy")
    with ui.column().classes("w-full gap-0 pl-8 pb-2").mark("position-lots") as details:
        if fund := fund_details(instrument):
            ui.label(" · ".join(fund)).classes("text-sm text-gray-500 pb-1").mark("fund-details")
        with ui.element("div").classes("grid gap-x-4 text-sm font-medium").style(columns):
            for header in headers if bond is None else (*headers, "Oprocentowanie", "Wartość"):
                ui.label(header).classes("text-right" if header != "Data zakupu" else "")
        for lot in position.lots:
            with ui.element("div").classes("grid gap-x-4 text-sm").style(columns):
                ui.label(format_date(lot.date))
                ui.label(format_quantity(lot.quantity)).classes("text-right")
                ui.label(format_pln(lot.cost)).classes("text-right")
                ui.label(format_pln(lot.tax_cost)).classes("text-right")
                if bond is not None:
                    with ui.column().classes("gap-0 items-end"):
                        _bond_rate(bond, lot, (lot,))
                    ui.label(format_pln(lot.quantity * bond.of(lot))).classes("text-right")
    details.visible = False
    return details


def _result_color(result: Decimal) -> str:
    return "text-positive" if result > 0 else "text-negative" if result < 0 else ""
