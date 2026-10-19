"""The Dochód pasywny tab (issue #93, spec 10): the View Scope's Dividends and interest received and the bond coupons
forecast, month by month in the chosen year, against the Monthly Income Goal kept in ``app_settings``, with the
coupons due over the next 12 months listed below."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_date, format_exact, format_percent, format_pln
from financial_app.domain.passive_income import (
    IncomeItem,
    IncomeKind,
    MonthIncome,
    income_by_month,
    monthly_average,
    parse_income_goal,
)
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.settings import PASSIVE_INCOME_GOAL, load_setting, save_setting
from financial_app.sources.nbp import NbpRates
from financial_app.sources.passive_income import income_items
from financial_app.ui.changes import TODAYS_VALUE
from financial_app.ui.charts import pln_bars_chart
from financial_app.ui.view_scope import ViewScope

MONTH_NAMES = (
    "Styczeń",
    "Luty",
    "Marzec",
    "Kwiecień",
    "Maj",
    "Czerwiec",
    "Lipiec",
    "Sierpień",
    "Wrzesień",
    "Październik",
    "Listopad",
    "Grudzień",
)
FORECAST = "Prognoza (kupony)"
MONTH_COLUMNS = "grid-template-columns: minmax(7rem, 1fr) repeat(3, minmax(7rem, 1fr)) minmax(10rem, 2fr)"
FORECAST_COLUMNS = "grid-template-columns: minmax(6rem, 1fr) minmax(8rem, 2fr) minmax(6rem, 1fr) minmax(7rem, 1fr)"


@dataclass
class PassiveIncomePage:
    """The Dochód pasywny tab of the View Scope; the year shown starts at the NBP Rates' today's and is not
    remembered."""

    # The changes it redraws on (ui/changes.py)
    CHANGES = TODAYS_VALUE

    engine: Engine
    rates: NbpRates
    scope: ViewScope
    year: int | None = field(default=None, init=False)

    def refresh(self) -> None:
        """Redraw the tab if it is on screen (e.g. after a save or a scope change)."""
        self.content.refresh()

    def build(self) -> None:
        ui.label("Dochód pasywny").classes("text-2xl font-bold")
        ui.label("Dywidendy i odsetki netto: otrzymane oraz prognozowane kupony obligacji.").classes(
            "text-sm text-gray-600"
        )
        with ui.column().classes("w-full max-w-screen-2xl").mark("passive-income"):
            self.content()

    @ui.refreshable_method
    def content(self) -> None:
        today = self.rates.today()
        year = self.year or today.year
        goal = _saved_goal(self.engine)
        items = income_items(self.engine, today)
        account_id = self.scope.account_id
        months = income_by_month(items, year, account_id)
        self._controls(year, goal)
        _tiles(months, monthly_average(items, today, account_id), goal)
        _chart(months, goal)
        _months(months, goal)
        _forecast(items, today, account_id, self.engine)

    def _controls(self, year: int, goal: Decimal | None) -> None:
        def show(chosen: int) -> None:
            self.year = chosen
            self.refresh()

        def save_goal() -> None:
            try:
                parsed = parse_income_goal(goal_input.value or "")
            except ValueError as error:
                ui.notify(str(error), type="warning")
                return
            save_setting(self.engine, PASSIVE_INCOME_GOAL, "" if parsed is None else str(parsed))
            self.refresh()

        with ui.row().classes("w-full items-center gap-4"):
            ui.button(icon="chevron_left", on_click=lambda: show(year - 1)).props(
                'flat round dense aria-label="Poprzedni rok"'
            ).mark("income-year-prev")
            ui.label(str(year)).classes("text-xl font-medium").mark("income-year")
            ui.button(icon="chevron_right", on_click=lambda: show(year + 1)).props(
                'flat round dense aria-label="Następny rok"'
            ).mark("income-year-next")
            ui.space()
            goal_input = ui.input(
                "Miesięczny cel dochodu (zł)", value="" if goal is None else format_exact(goal)
            ).classes("w-56")
            goal_input.mark("income-goal")
            ui.button("Zapisz cel", on_click=save_goal).props("flat no-caps").mark("income-goal-save")


def _saved_goal(engine: Engine) -> Decimal | None:
    text = load_setting(engine, PASSIVE_INCOME_GOAL)
    return Decimal(text) if text else None


def _tiles(months: list[MonthIncome], average: Decimal, goal: Decimal | None) -> None:
    received = sum((month.received_total for month in months), Decimal(0))
    forecast = sum((month.forecast_total for month in months), Decimal(0))
    average_note = "" if goal is None else f"{_progress(average / goal)} celu"
    tiles = (
        ("year-received", "Otrzymane w roku", format_pln(received), ""),
        ("year-forecast", "Prognoza w roku", format_pln(forecast), "kupony jeszcze niewpisane"),
        ("average", "Średnio miesięcznie", format_pln(average), f"ostatnie 12 miesięcy {average_note}".strip()),
        ("monthly-goal", "Cel miesięczny", "—" if goal is None else format_pln(goal), ""),
    )
    with (
        ui.element("div")
        .classes("grid w-full gap-4")
        .style("grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr))")
    ):
        for key, title, text, note in tiles:
            with ui.card().classes("gap-1"):
                ui.label(title).classes("text-sm text-gray-500")
                ui.label(text).classes("text-xl font-medium").mark(f"income-{key}")
                if note:
                    ui.label(note).classes("text-xs text-gray-500")


def _chart(months: list[MonthIncome], goal: Decimal | None) -> None:
    series = {kind.label: [month.received.get(kind, Decimal(0)) for month in months] for kind in IncomeKind}
    series[FORECAST] = [month.forecast_total for month in months]
    pln_bars_chart(
        "Dochód pasywny w miesiącach",
        "passive-income",
        [name[:3] for name in MONTH_NAMES],
        series,
        None if goal is None else ("Cel", goal),
    )


def _months(months: list[MonthIncome], goal: Decimal | None) -> None:
    with ui.card().classes("w-full overflow-x-auto").mark("income-months"):
        with ui.element("div").classes("grid w-full gap-x-4 text-sm font-medium").style(MONTH_COLUMNS):
            for header in ("Miesiąc", "Otrzymane", "Prognoza", "Razem", "Cel"):
                ui.label(header)
        for month in months:
            line = ui.element("div").classes("grid w-full items-center gap-x-4 border-t py-1 text-sm")
            with line.style(MONTH_COLUMNS).mark("income-month"):
                ui.label(MONTH_NAMES[month.month.month - 1]).classes("font-medium")
                ui.label(format_pln(month.received_total)).classes("text-right")
                ui.label(format_pln(month.forecast_total)).classes("text-right")
                ui.label(format_pln(month.total)).classes("text-right")
                progress = month.progress(goal)
                if progress is None:
                    ui.label("")
                else:
                    with ui.row().classes("items-center gap-2 no-wrap"):
                        ui.linear_progress(float(min(progress, Decimal(1))), show_value=False).classes("w-24")
                        ui.label(_progress(progress))


def _forecast(items: list[IncomeItem], today: date, account_id: int | None, engine: Engine) -> None:
    coming = [i for i in items if i.forecast and account_id in (None, i.account_id)]
    names = {i.id: i.name for i in list_instruments(engine)}
    accounts = {a.id: a.name for a in list_accounts(engine)}
    with ui.card().classes("w-full").mark("income-forecast"):
        ui.label("Prognozowane kupony (12 miesięcy)").classes("text-lg font-medium")
        if not coming:
            ui.label("Brak kuponów do wypłaty.").classes("text-gray-500")
            return
        with ui.element("div").classes("grid w-full gap-x-4 text-sm font-medium").style(FORECAST_COLUMNS):
            for header in ("Data", "Seria", "Konto", "Netto"):
                ui.label(header)
        for item in coming:
            line = ui.element("div").classes("grid w-full gap-x-4 border-t py-1 text-sm")
            with line.style(FORECAST_COLUMNS).mark("income-forecast-row"):
                due = format_date(item.day)
                ui.label(due if item.day > today else f"{due} (do zatwierdzenia)")
                ui.label(names.get(item.instrument_id or 0, ""))
                ui.label(accounts.get(item.account_id, ""))
                ui.label(format_pln(item.amount)).classes("text-right")


def _progress(fraction: Decimal) -> str:
    return format_percent(fraction * 100, decimals=0)
