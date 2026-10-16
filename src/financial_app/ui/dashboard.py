"""The Dashboard tab (issues #72, #73 and #89, spec section 5): the View Scope's totals and charts, and in the Total
scope the Accounts treemap and ranking.

Positions are valued like in the Portfolio (``domain.valuation``, foreign ones at the NBP Rate from the last business
day before today); Net Deposits come from History, "—" while it is computed. The "po podatku" toggle (not remembered)
takes the estimated Belka on Regular Accounts' unrealised gains off their results.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from nicegui import ui
from nicegui.events import ValueChangeEventArguments
from sqlalchemy import Engine

from financial_app.domain.account_ranking import ranking
from financial_app.domain.dashboard import AccountRow, CurrencyShare, Totals
from financial_app.domain.formatting import format_count, format_percent, format_pln
from financial_app.domain.portfolio_history import DayValue
from financial_app.sources.dashboard import todays_dashboard
from financial_app.sources.nbp import NbpRates
from financial_app.sources.prices import RefreshStatus, last_refresh, refresh_summary, unpriced_instruments
from financial_app.ui.account_ranking import AccountRanking, accounts_treemap
from financial_app.ui.charts import dashboard_charts
from financial_app.ui.contribution_limits import limits_section
from financial_app.ui.info import card_title
from financial_app.ui.periods import PeriodChoice, period_selector
from financial_app.ui.strategy import PlannedDeposit, strategy_section
from financial_app.ui.view_scope import ViewScope

DASH = "—"
# Behind the "i" of the tiles and tables that need explaining, by their marker
TILE_INFO = {
    "net-deposits": "Wszystkie wpłaty na konta minus wszystkie wypłaty: ile własnych pieniędzy naprawdę włożyłeś.",
    "value": "Ile jest dziś warty portfel: otwarte pozycje według ostatnich cen i gotówka, przeliczone na złote.",
    "open-positions": "Dzisiejsza wartość posiadanych instrumentów, wycenionych po ostatnich cenach.",
    "unrealized": (
        "Zysk lub strata na tym, co nadal masz: dzisiejsza wartość pozycji minus ich koszt zakupu (z wynikiem "
        "walutowym gotówki w walucie obcej). Stanie się zrealizowany dopiero przy sprzedaży. Z „Po podatku” "
        "jest pomniejszony o szacowany podatek."
    ),
    "realized": "Zysk lub strata na tym, co już sprzedałeś: cena sprzedaży minus koszt zakupu tych jednostek.",
    "dividends": "Dywidendy i odsetki netto, czyli po podatku pobranym u źródła.",
    "xirr": (
        "Roczna stopa zwrotu z uwzględnieniem terminów i kwot wpłat i wypłat, jak oprocentowanie lokaty dającej "
        "ten sam wynik. Przy krótkim okresie bywa przesadnie wysoka lub niska."
    ),
    "estimated-tax": (
        "Ile zapłaciłbyś, sprzedając wszystko dziś: podatek Belki od niezrealizowanych zysków na zwykłych kontach "
        "(nie IKE/IKZE) oraz opłata i podatek przy przedterminowym wykupie obligacji."
    ),
}
CURRENCY_INFO = (
    "Ile majątku trzymasz w każdej walucie: pozycje według waluty notowania i gotówka, w złotych, oraz ich udział. "
    "Waluty obce to ryzyko kursowe, ale też źródło efektu walutowego w wyniku."
)


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
    after_tax: bool = False
    ranking: AccountRanking = field(default_factory=AccountRanking)

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
        ui.switch("Po podatku", value=self.after_tax, on_change=self._toggle_after_tax).mark("after-tax")
        _totals(board.totals, self.after_tax)
        _account_table(board.accounts, self.after_tax)
        limits_section(self.engine, today.transactions, today.accounts, self.rates.today(), self.scope.account_id)
        if self.scope.account_id is None:
            rows = ranking(board.accounts, self.after_tax)
            accounts_treemap(rows, self.scope.switch)
            self.ranking.build(rows)
        _currency_exposure(board.currencies)
        strategy = strategy_section(self.engine, today, self.scope.account_id, self.planned)
        targets = {row.asset_class: row.target.percent for row in strategy.view.rows if row.target is not None}
        account_names = {account.id: account.name for account in today.accounts}
        sources = board.sources.after_tax(board.totals.estimated_tax) if self.after_tax else board.sources
        dashboard_charts(
            board, today.transactions, account_names, days, self.scope.account_id, period, targets, sources
        )

    def _toggle_after_tax(self, event: ValueChangeEventArguments[bool | None]) -> None:
        self.after_tax = bool(event.value)
        self.refresh()


def _totals(totals: Totals, after_tax: bool) -> None:
    """The tiles; ``after_tax`` adds the estimated Belka and takes it off the unrealised result."""
    tiles: list[tuple[str, str, str | None]] = [
        ("net-deposits", "Wpłaty netto", None if totals.net_deposits is None else format_pln(totals.net_deposits)),
        ("value", "Wartość konta", format_pln(totals.value)),
        ("open-positions", "Otwarte pozycje", format_pln(totals.open_positions)),
        ("cash", "Gotówka", format_pln(totals.cash)),
        (
            "unrealized",
            "Niezrealizowany zysk po podatku" if after_tax else "Niezrealizowany zysk",
            format_pln(totals.unrealized_after(after_tax), signed=True),
        ),
        ("realized", "Zrealizowany zysk", format_pln(totals.realized, signed=True)),
        ("dividends", "Dywidendy i odsetki", format_pln(totals.dividends)),
        ("costs", "Prowizje i koszty", format_pln(totals.costs)),
        ("xirr", "XIRR", None if totals.xirr is None else format_percent(totals.xirr * 100)),
    ]
    if after_tax:
        tiles.append(("estimated-tax", "Szacowany podatek i opłaty", format_pln(totals.estimated_tax)))
    with (
        ui.element("div")
        .classes("grid w-full gap-4")
        .style("grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr))")
    ):
        for key, title, text in tiles:
            with ui.card().classes("gap-1"):
                card_title(title, TILE_INFO.get(key), f"total-{key}", "text-sm text-gray-500")
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


def _account_table(rows: tuple[AccountRow, ...], after_tax: bool) -> None:
    """A row per Account with its totals; an Account excluding its FX result from the result says so; ``after_tax``
    takes each Account's estimated Belka off its unrealised result."""
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
                format_pln(totals.unrealized_after(after_tax), signed=True),
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
        card_title("Waluty w portfelu", CURRENCY_INFO, "currency-exposure")
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
