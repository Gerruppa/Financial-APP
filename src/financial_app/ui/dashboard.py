"""The Dashboard tab (issues #72 and #73, spec section 5): the View Scope's totals and charts.

Positions are valued like in the Portfolio (``domain.valuation``, foreign ones at the NBP Rate from the last business
day before today); Net Deposits come from History, "—" while it is computed.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.dashboard import AccountRow, CurrencyShare, Totals
from financial_app.domain.formatting import format_count, format_percent, format_pln
from financial_app.domain.portfolio_history import DayValue
from financial_app.sources.dashboard import todays_dashboard
from financial_app.sources.nbp import NbpRates
from financial_app.sources.prices import RefreshStatus, last_refresh, refresh_summary, unpriced_instruments
from financial_app.ui.charts import dashboard_charts
from financial_app.ui.periods import PeriodChoice, period_selector
from financial_app.ui.strategy import PlannedDeposit, strategy_section
from financial_app.ui.view_scope import ViewScope

DASH = "—"


@dataclass
class DashboardPage:
    """The Dashboard tab of the View Scope, under the period selector; ``history`` gives History's days once
    computed. It never offers editing controls."""

    engine: Engine
    rates: NbpRates
    scope: ViewScope
    period: PeriodChoice
    history: Callable[[], list[DayValue] | None]
    planned: PlannedDeposit = field(default_factory=PlannedDeposit)

    def refresh(self) -> None:
        """Redraw the Dashboard if it is on screen (e.g. after a save, a price refresh or History computed)."""
        self.content.refresh()

    def __post_init__(self) -> None:
        self.period.on_change(self.refresh)

    def build(self) -> None:
        ui.label("Dashboard").classes("text-2xl font-bold")
        period_selector(self.period)
        with ui.column().classes("w-full max-w-6xl").mark("dashboard"):
            self.content()

    @ui.refreshable_method
    def content(self) -> None:
        days = self.history()
        period = self.period.dates()
        today = todays_dashboard(self.engine, self.rates, self.scope.account_id, days, period)
        board = today.board
        _prices_line(last_refresh(self.engine), len(unpriced_instruments(self.engine)))
        _totals(board.totals)
        _account_table(board.accounts)
        _currency_exposure(board.currencies)
        strategy = strategy_section(self.engine, today, self.scope.account_id, self.planned)
        targets = {row.asset_class: row.target.percent for row in strategy.view.rows if row.target is not None}
        account_names = {account.id: account.name for account in today.accounts}
        dashboard_charts(board, today.transactions, account_names, days, self.scope.account_id, period, targets)


def _totals(totals: Totals) -> None:
    tiles = (
        ("net-deposits", "Wpłaty netto", None if totals.net_deposits is None else format_pln(totals.net_deposits)),
        ("value", "Wartość konta", format_pln(totals.value)),
        ("open-positions", "Otwarte pozycje", format_pln(totals.open_positions)),
        ("cash", "Gotówka", format_pln(totals.cash)),
        ("unrealized", "Niezrealizowany zysk", format_pln(totals.unrealized, signed=True)),
        ("realized", "Zrealizowany zysk", format_pln(totals.realized, signed=True)),
        ("dividends", "Dywidendy i odsetki", format_pln(totals.dividends)),
        ("costs", "Prowizje i koszty", format_pln(totals.costs)),
        ("xirr", "XIRR", None if totals.xirr is None else format_percent(totals.xirr * 100)),
    )
    with (
        ui.element("div")
        .classes("grid w-full gap-4")
        .style("grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr))")
    ):
        for key, title, text in tiles:
            with ui.card().classes("gap-1"):
                ui.label(title).classes("text-sm text-gray-500")
                ui.label(DASH if text is None else text).classes("text-xl font-medium").mark(f"total-{key}")


ACCOUNT_COLUMNS = "grid-template-columns: minmax(8rem, 2fr) repeat(9, minmax(6rem, 1fr)) minmax(8rem, 1.5fr)"
ACCOUNT_HEADERS = (
    "Konto",
    "Wpłaty netto",
    "Wartość",
    "Otwarte pozycje",
    "Gotówka",
    "Niezrealizowany",
    "Zrealizowany",
    "XIRR",
    "Dywidendy",
    "Prowizje i koszty",
    "",
)


def _account_table(rows: tuple[AccountRow, ...]) -> None:
    """A row per Account with its totals; an Account excluding its FX result from the result says so."""
    with ui.card().classes("w-full overflow-x-auto").mark("account-table"):
        with ui.element("div").classes("grid w-full gap-x-4 border-b py-1 text-sm font-medium").style(ACCOUNT_COLUMNS):
            for header in ACCOUNT_HEADERS:
                ui.label(header).classes("text-right" if header not in ("Konto", "") else "")
        for row in rows:
            totals = row.totals
            cells = (
                DASH if totals.net_deposits is None else format_pln(totals.net_deposits),
                format_pln(totals.value),
                format_pln(totals.open_positions),
                format_pln(totals.cash),
                format_pln(totals.unrealized, signed=True),
                format_pln(totals.realized, signed=True),
                DASH if totals.xirr is None else format_percent(totals.xirr * 100),
                format_pln(totals.dividends),
                format_pln(totals.costs),
            )
            line = ui.element("div").classes("grid w-full gap-x-4 border-b py-1 text-sm").style(ACCOUNT_COLUMNS)
            with line.mark("account-row"):
                ui.label(row.account.name).classes("font-medium")
                for cell in cells:
                    ui.label(cell).classes("text-right")
                ui.label("bez wyniku walutowego" if row.account.exclude_fx_result else "").classes("text-gray-500")


CURRENCY_COLUMNS = "grid-template-columns: 4rem repeat(2, minmax(6rem, 10rem))"


def _currency_exposure(currencies: tuple[CurrencyShare, ...]) -> None:
    """The value held in each currency (Positions by their quote currency, and cash) and its share, largest first."""
    with ui.card().mark("currency-exposure"):
        ui.label("Waluty w portfelu").classes("text-lg font-medium")
        with ui.element("div").classes("grid gap-x-4 text-sm font-medium").style(CURRENCY_COLUMNS):
            for header in ("Waluta", "Wartość", "Udział"):
                ui.label(header).classes("text-right" if header != "Waluta" else "")
        for currency in currencies:
            line = ui.element("div").classes("grid gap-x-4 text-sm").style(CURRENCY_COLUMNS)
            with line.mark("currency-row"):
                ui.label(currency.currency)
                ui.label(format_pln(currency.value)).classes("text-right")
                ui.label(format_percent(currency.share * 100)).classes("text-right")


def _prices_line(refresh: RefreshStatus | None, unpriced: int) -> None:
    """When prices were last refreshed and how many Instruments failed, as in the header; the Instruments without a
    price lead to their list in Ustawienia."""
    with ui.row().classes("w-full items-center gap-4 text-sm").mark("dashboard-prices"):
        ui.label(refresh_summary(refresh)).classes("text-negative" if refresh and refresh.failures else "text-gray-600")
        if unpriced:
            text = format_count(unpriced, "instrument bez wyceny", "instrumenty bez wyceny", "instrumentów bez wyceny")
            ui.link(text, "/ustawienia")
