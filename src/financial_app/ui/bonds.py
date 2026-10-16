"""The Obligacje tab (spec 3.4.1, L-4): the Bond Series held in the View Scope, each expanding to its Lots, with what
was paid in, the current period and its rate (labelled when MF has not published it), the gross value, the net value
after the early-redemption fee and the tax the Account's Tax Regime withholds, the next anniversary and the maturity.
Above them, the "Do zatwierdzenia" list of the Lots held past their maturity (L-6); below them, the calendar of the
coupons, anniversaries and maturities over the next 12 months (L-9)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.bond_calendar import CalendarEvent, EventKind, bond_calendar
from financial_app.domain.bond_holdings import LotHolding, SeriesHolding, bond_holdings, bond_totals
from financial_app.domain.bond_valuation import BondValue, RateLabel, rate_text
from financial_app.domain.bonds import BondType
from financial_app.domain.formatting import format_date, format_pln, format_quantity
from financial_app.sources.nbp import NbpRates
from financial_app.sources.todays_view import todays_view
from financial_app.ui.bond_drafts import drafts_list
from financial_app.ui.changes import TODAYS_VALUE
from financial_app.ui.view_scope import ViewScope

COLUMNS = "grid-template-columns: minmax(8rem, 2fr) repeat(7, minmax(6rem, 1fr))"
HEADERS = (
    "Seria",
    "Liczba",
    "Wpłacono",
    "Oprocentowanie",
    "Wartość brutto",
    "Wartość netto",
    "Następna rocznica",
    "Wykup",
)
LOT_HEADERS = ("Data zakupu", *HEADERS[1:])
CALENDAR_COLUMNS = (
    "grid-template-columns: minmax(6rem, 1fr) minmax(8rem, 2fr) minmax(12rem, 3fr) repeat(2, minmax(6rem, 1fr))"
)
CALENDAR_HEADERS = ("Data", "Seria", "Zdarzenie", "Brutto", "Netto")


@dataclass
class BondsPage:
    """The Obligacje tab of the View Scope; the bonds are valued at the end of the NBP Rates' today, as the
    Portfolio values them."""

    # The changes it redraws on (ui/changes.py)
    CHANGES = TODAYS_VALUE

    engine: Engine
    rates: NbpRates
    scope: ViewScope
    # Called once a Draft is confirmed, as after any saved Transaction
    on_saved: Callable[[], None] = field(default=lambda: None)

    def refresh(self) -> None:
        """Redraw the tab if it is on screen (e.g. after a save, a price refresh or a scope change)."""
        self.content.refresh()

    def build(self) -> None:
        ui.label("Obligacje").classes("text-2xl font-bold")
        with ui.column().classes("w-full max-w-6xl gap-0").mark("bonds"):
            self.content()

    @ui.refreshable_method
    def content(self) -> None:
        view = todays_view(self.engine, self.rates)
        today = view.today
        drafts_list(self.engine, today, self.scope.account_id, self.on_saved)
        positions, instruments, accounts, bonds = view.positions, view.instruments, view.accounts, view.bonds
        holdings = bond_holdings(positions, instruments, accounts, bonds, today, self.scope.account_id)
        if not holdings:
            ui.label(
                "Brak obligacji skarbowych w portfelu. Zakup obligacji dodasz przyciskiem „+” w trybie obligacji."
            ).classes("text-gray-500").mark("bonds-empty")
            return
        with ui.element("div").classes("grid w-full gap-x-4 border-b py-1 font-medium").style(COLUMNS):
            for header in HEADERS:
                ui.label(header).classes("" if header == "Seria" else "text-right")
        for holding in holdings:
            self._series_row(holding)
        _totals(holdings)
        self._calendar(bond_calendar(positions, instruments, accounts, bonds, today, self.scope.account_id))

    def _series_row(self, holding: SeriesHolding) -> None:
        row = ui.element("div").classes("grid w-full gap-x-4 border-b py-1 cursor-pointer hover:bg-gray-100")
        with row.style(COLUMNS).mark("bond-row"):
            with ui.column().classes("gap-0"):
                ui.label(holding.instrument.name).classes("font-medium")
                if self.scope.account_id is None:
                    ui.label(holding.account.name).classes("text-xs text-gray-500")
            ui.label(format_quantity(holding.quantity)).classes("text-right")
            ui.label(format_pln(holding.paid)).classes("text-right")
            _rate_cell(holding.current, holding.label)
            ui.label(format_pln(holding.gross)).classes("text-right")
            _net_cell(holding.net)
            _date_cell(holding.next_anniversary)
            _date_cell(holding.maturity)
        with ui.column().classes("w-full gap-0 pl-8 pb-2").mark("bond-lots") as lots:
            with ui.element("div").classes("grid w-full gap-x-4 text-sm font-medium").style(COLUMNS):
                for header in LOT_HEADERS:
                    ui.label(header).classes("" if header == "Data zakupu" else "text-right")
            for held in holding.lots:
                _lot_row(held)
        lots.visible = False
        row.on("click", lambda: lots.set_visibility(not lots.visible))

    def _calendar(self, events: list[CalendarEvent]) -> None:
        ui.label("Kalendarz: najbliższe 12 miesięcy").classes("text-lg font-bold mt-6")
        with ui.column().classes("w-full gap-0").mark("bond-calendar"):
            if not events:
                ui.label("W najbliższych 12 miesiącach nie przypadają odsetki, rocznice ani wykupy.").classes(
                    "text-gray-500"
                ).mark("calendar-empty")
                return
            with ui.element("div").classes("grid w-full gap-x-4 border-b py-1 font-medium").style(CALENDAR_COLUMNS):
                for header in CALENDAR_HEADERS:
                    ui.label(header).classes("text-right" if header in ("Brutto", "Netto") else "")
            for event in events:
                self._calendar_row(event)

    def _calendar_row(self, event: CalendarEvent) -> None:
        row = ui.element("div").classes("grid w-full gap-x-4 border-b py-1").style(CALENDAR_COLUMNS)
        with row.mark("calendar-row"):
            ui.label(format_date(event.day))
            with ui.column().classes("gap-0"):
                ui.label(event.instrument.name).classes("font-medium")
                lot = f"zakup {format_date(event.lot.date)} · {format_quantity(event.quantity)} szt."
                if self.scope.account_id is None:
                    lot = f"{event.account.name} · {lot}"
                ui.label(lot).classes("text-xs text-gray-500")
            with ui.column().classes("gap-0"):
                ui.label(_event_text(event))
                if event.label is not None:
                    ui.label(event.label.value).classes("text-xs text-orange-700").mark("calendar-rate-label")
            _amount_cell(event.gross)
            _amount_cell(event.net)


def _event_text(event: CalendarEvent) -> str:
    rate = event.rate_text
    match event.kind:
        case EventKind.COUPON:
            return f"Odsetki · {rate}"
        case EventKind.ANNIVERSARY if event.bond_type is BondType.TOS:
            return f"Rocznica · kapitalizacja odsetek, {rate}"
        case EventKind.ANNIVERSARY:
            return f"Rocznica · nowe oprocentowanie {rate}"
        case EventKind.MATURITY:
            return "Wykup"


def _amount_cell(amount: Decimal | None) -> None:
    ui.label("—" if amount is None else format_pln(amount)).classes("text-right")


def _lot_row(held: LotHolding) -> None:
    with ui.element("div").classes("grid w-full gap-x-4 text-sm").style(COLUMNS):
        ui.label(format_date(held.lot.date))
        ui.label(format_quantity(held.lot.quantity)).classes("text-right")
        ui.label(format_pln(held.lot.cost)).classes("text-right")
        _rate_cell(held.value, None if held.value is None else held.value.label)
        ui.label(format_pln(held.gross)).classes("text-right")
        with ui.column().classes("gap-0 items-end"):
            if held.net is None:
                ui.label("—").classes("text-gray-500")
            else:
                ui.label(format_pln(held.net))
                ui.label(f"opłata {format_pln(held.fee)} · podatek {format_pln(held.tax)}").classes(
                    "text-xs text-gray-500"
                )
        _date_cell(held.next_anniversary)
        _date_cell(held.maturity)


def _rate_cell(value: BondValue | None, label: RateLabel | None) -> None:
    """The period's rate and number (no number for a bond running months), with the label of the most uncertain rate
    the value rests on; "po koszcie" for a Series not valued yet."""
    with ui.column().classes("gap-0 items-end"):
        if value is None:
            ui.label("po koszcie").classes("text-gray-500")
            return
        ui.label(rate_text(value))
        if label is not None:
            ui.label(label.value).classes("text-xs text-orange-700").mark("bond-rate-label")


def _net_cell(net: Decimal | None) -> None:
    if net is None:
        ui.label("—").classes("text-right text-gray-500").mark("bond-net")
    else:
        ui.label(format_pln(net)).classes("text-right font-medium").mark("bond-net")


def _date_cell(day: date | None) -> None:
    ui.label("—" if day is None else format_date(day)).classes("text-right")


def _totals(holdings: list[SeriesHolding]) -> None:
    totals = bond_totals(holdings)
    with ui.element("div").classes("grid w-full gap-x-4 py-1 font-medium").style(COLUMNS).mark("bond-totals"):
        ui.label("Razem")
        ui.label("")
        ui.label(format_pln(totals.paid)).classes("text-right")
        ui.label("")
        ui.label(format_pln(totals.gross)).classes("text-right")
        ui.label(format_pln(totals.net)).classes("text-right")
