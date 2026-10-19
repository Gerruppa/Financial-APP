"""The Dashboard tab (issues #72, #73 and #89, spec section 5): the View Scope's totals and charts, and in the Total
scope the Accounts treemap and ranking. Its layout follows variant A of the #174 prototype: a main card with the value
and its chart, tiles with coloured icons, and the Accounts as cards with the table one click away.

Positions are valued like in the Portfolio (``domain.valuation``, foreign ones at the NBP Rate from the last business
day before today); Net Deposits come from History, "—" while it is computed. The "po podatku" toggle (not remembered)
takes the estimated Belka on Regular Accounts' unrealised gains off their results. The tiles, sections and charts
hidden in Wygląd i widoczność (``layout``, issue #155) are left out.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from nicegui import ui
from nicegui.events import ValueChangeEventArguments
from sqlalchemy import Engine

from financial_app.domain.account_ranking import ranking
from financial_app.domain.charts import value_series
from financial_app.domain.dashboard import AccountRow, CurrencyShare, Totals
from financial_app.domain.formatting import format_count, format_day_time, format_percent, format_pln
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.valuation_snapshots import SnapshotChange
from financial_app.sources.dashboard import todays_dashboard
from financial_app.sources.nbp import NbpRates
from financial_app.sources.prices import RefreshStatus, last_refresh, refresh_summary, unpriced_instruments
from financial_app.sources.valuation_snapshots import change_since_snapshot
from financial_app.ui.account_ranking import AccountRanking, accounts_treemap
from financial_app.ui.changes import Change
from financial_app.ui.charts import dashboard_charts, hero_value_chart, sparkline
from financial_app.ui.contribution_limits import limits_section
from financial_app.ui.help import HELP_PATH
from financial_app.ui.info import card_title
from financial_app.ui.investment_goal import goal_tile
from financial_app.ui.periods import PeriodChoice, period_selector
from financial_app.ui.strategy import PlannedDeposit, scope_strategy, strategy_section
from financial_app.ui.view_scope import ViewScope
from financial_app.ui.visibility import Layout

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
# Each tile's icon with its circle's background and the icon's colour in Jasny (Golden makes them all gold)
TILE_ICONS = {
    "net-deposits": ("account_balance_wallet", "#dcfce7", "#16a34a"),
    "value": ("pie_chart", "#ede9fe", "#6d28d9"),
    "open-positions": ("storage", "#dbeafe", "#2563eb"),
    "cash": ("account_balance", "#fef3c7", "#d97706"),
    "unrealized": ("trending_up", "#dcfce7", "#16a34a"),
    "realized": ("bar_chart", "#dcfce7", "#16a34a"),
    "dividends": ("paid", "#dbeafe", "#2563eb"),
    "costs": ("sell", "#fee2e2", "#dc2626"),
    "xirr": ("percent", "#dbeafe", "#2563eb"),
    "estimated-tax": ("receipt_long", "#fee2e2", "#dc2626"),
}
# The circles of the Accounts' cards, in the order of the Accounts
ACCOUNT_COLOURS = ("#f97316", "#2563eb", "#eab308", "#7c3aed", "#e11d48", "#0d9488")
CURRENCY_INFO = (
    "Ile majątku trzymasz w każdej walucie: pozycje według waluty notowania i gotówka, w złotych, oraz ich udział. "
    "Waluty obce to ryzyko kursowe, ale też źródło efektu walutowego w wyniku."
)


@dataclass
class DashboardPage:
    """The Dashboard tab of the View Scope, under the period selector; ``history`` gives History's days once
    computed. It never offers editing controls."""

    # The changes it redraws on (ui/changes.py)
    CHANGES = frozenset({Change.SCOPE, Change.HISTORY, Change.LAYOUT})

    engine: Engine
    rates: NbpRates
    scope: ViewScope
    period: PeriodChoice
    history: Callable[[], list[DayValue] | None]
    layout: Layout
    planned: PlannedDeposit = field(default_factory=PlannedDeposit)
    after_tax: bool = False
    ranking: AccountRanking = field(default_factory=AccountRanking)
    # "Twoje konta i aktywa" as cards or as the Account table, not remembered
    accounts_view: str = "cards"

    def refresh(self) -> None:
        """Redraw the Dashboard if it is on screen (e.g. after a save, a price refresh or History computed)."""
        self.content.refresh()

    def __post_init__(self) -> None:
        self.period.on_change(self.refresh)

    def build(self) -> None:
        with ui.column().classes("gap-0"):
            ui.label("Dashboard").classes("text-3xl font-bold")
            ui.label("Przegląd Twoich inwestycji i wyników portfela").classes("k-muted")
        with ui.column().classes("w-full max-w-screen-2xl gap-4").mark("dashboard"):
            self.content()

    @ui.refreshable_method
    def content(self) -> None:
        days = self.history()
        period = self.period.dates()
        today = todays_dashboard(self.engine, self.rates, self.scope.account_id, days, period)
        board = today.board
        shows = self.layout.shows
        if not today.transactions:
            _first_steps()
        snapshot = None
        if shows("since-snapshot"):
            snapshot = change_since_snapshot(self.engine, self.scope.account_id, board.totals, self.period.today())
        self._hero(board.totals, snapshot, days, period)
        with ui.row().classes("w-full items-center gap-4"):
            _prices_line(last_refresh(self.engine), len(unpriced_instruments(self.engine)))
            ui.space()
            ui.switch("Po podatku", value=self.after_tax, on_change=self._toggle_after_tax).mark("after-tax")
        _totals(board.totals, self.after_tax, shows)
        if shows("investment-goal"):
            # The goal's progress follows the "Po podatku" toggle
            value = board.totals.value_after(self.after_tax)
            goal_tile(self.engine, self.rates, self.scope.account_id, value, days, self.period.today(), self.refresh)
        if shows("account-table"):
            self.accounts_section(board.accounts, days, period)
        if shows("contribution-limits"):
            limits_section(self.engine, today.transactions, today.accounts, self.rates.today(), self.scope.account_id)
        if self.scope.account_id is None and shows("account-ranking"):
            rows = ranking(board.accounts, self.after_tax)
            accounts_treemap(rows, self.scope.switch)
            self.ranking.build(rows)
        if shows("currency-exposure"):
            _currency_exposure(board.currencies)
        # The allocation chart shows the strategy's targets even with its section hidden
        if shows("strategy"):
            strategy = strategy_section(self.engine, today, self.scope.account_id, self.planned)
        else:
            strategy = scope_strategy(self.engine, today, self.scope.account_id, self.planned.amount)
        targets = {row.asset_class: row.target.percent for row in strategy.view.rows if row.target is not None}
        account_names = {account.id: account.name for account in today.accounts}
        sources = board.sources.after_tax(board.totals.estimated_tax) if self.after_tax else board.sources
        dashboard_charts(
            board, today.transactions, account_names, days, self.scope.account_id, period, targets, sources, shows
        )

    def _toggle_after_tax(self, event: ValueChangeEventArguments[bool | None]) -> None:
        self.after_tax = bool(event.value)
        self.refresh()

    def _hero(
        self,
        totals: Totals,
        snapshot: SnapshotChange | None,
        days: list[DayValue] | None,
        period: tuple[date, date],
    ) -> None:
        """The main card: the value with its change since the last Valuation Snapshot, beside the period selector
        and the value over the period (issue #174)."""
        with ui.card().classes("w-full p-6").mark("dashboard-hero"):
            with ui.row().classes("w-full items-center gap-8"):
                with ui.column().classes("gap-1 min-w-72"):
                    ui.label("Wartość portfela").classes("k-muted")
                    ui.label(format_pln(totals.value)).classes("text-5xl font-bold k-hero").mark("hero-value")
                    _since_snapshot(snapshot)
                with ui.column().classes("grow gap-2 min-w-96 items-end"):
                    period_selector(self.period)
                    if days is None:
                        ui.label("Wykres wartości: wyliczanie historii…").classes("k-muted").mark("chart-hero-pending")
                    else:
                        hero_value_chart(days, *period, self.scope.account_id)

    @ui.refreshable_method
    def accounts_section(
        self, rows: tuple[AccountRow, ...], days: list[DayValue] | None, period: tuple[date, date]
    ) -> None:
        """ "Twoje konta i aktywa": a card per Account, or the Account table one click away (issue #174)."""
        with ui.card().classes("w-full p-6 gap-4").mark("account-table"):
            with ui.row().classes("w-full items-center gap-2"):
                ui.label("Twoje konta i aktywa").classes("text-lg font-semibold grow")
                for view, label, icon in (("cards", "Karty", "view_module"), ("table", "Tabela", "table_rows")):
                    button = ui.button(label, icon=icon, on_click=lambda v=view: self._show_accounts(v))
                    chosen = view == self.accounts_view
                    button.props("no-caps dense " + ("unelevated color=primary" if chosen else "flat color=grey-7"))
                    button.classes("px-3").mark(f"accounts-view-{view}")
            if self.accounts_view == "table":
                _account_table(rows, self.after_tax)
                return
            with (
                ui.element("div")
                .classes("grid w-full gap-4")
                .style("grid-template-columns: repeat(auto-fill, minmax(17rem, 1fr))")
            ):
                for index, row in enumerate(rows):
                    values = [] if days is None else value_series(days, *period, row.account.id)
                    self._account_card(index, row, [point.value for point in values])

    def _account_card(self, index: int, row: AccountRow, values: list[Decimal]) -> None:
        """An Account's value and P&L since its first Transaction over its value in the period; clicking it opens
        its View Scope."""
        totals = row.totals
        profit = totals.profit_after(self.after_tax)
        share = totals.profit_share(self.after_tax)
        if profit is None:
            text = DASH
        else:
            text = format_pln(profit, signed=True)
            if share is not None:
                text += f" ({format_percent(share * 100, signed=True)})"
        card = ui.card().classes("gap-1 p-4 cursor-pointer").mark("account-card")
        card.on("click", lambda: self.scope.switch(row.account.id))
        with card:
            with ui.row().classes("w-full items-center no-wrap gap-3"):
                colour = ACCOUNT_COLOURS[index % len(ACCOUNT_COLOURS)]
                with ui.element("div").classes("k-icon shrink-0").style(f"background:{colour}; color:#fff"):
                    ui.icon("account_balance").classes("text-xl")
                ui.label(row.account.name).classes("font-medium grow")
                ui.icon("chevron_right").classes("k-muted")
            with ui.row().classes("w-full items-end no-wrap"):
                with ui.column().classes("gap-0 grow"):
                    ui.label(format_pln(totals.value)).classes("text-lg font-semibold")
                    colour_class = "" if profit is None else "text-negative" if profit < 0 else "text-positive"
                    ui.label(text).classes(f"text-sm {colour_class}")
                if values:
                    sparkline(values, str(row.account.id))

    def _show_accounts(self, view: str) -> None:
        self.accounts_view = view
        self.accounts_section.refresh()


def _totals(totals: Totals, after_tax: bool, shows: Callable[[str], bool]) -> None:
    """The tiles ``shows`` shows by their ``tile-`` key; ``after_tax`` adds the estimated Belka and takes it off the
    unrealised result."""
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
    tiles = [tile for tile in tiles if shows(f"tile-{tile[0]}")]
    if not tiles:
        return
    # What part of the Portfolio the cash and the costs are, under their amounts
    notes = {key: totals.share_of_value(amount) for key, amount in (("cash", totals.cash), ("costs", totals.costs))}
    with (
        ui.element("div")
        .classes("grid w-full gap-4")
        .style("grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr))")
    ):
        for key, title, text in tiles:
            icon, background, colour = TILE_ICONS[key]
            with ui.card().classes("p-4"), ui.row().classes("w-full items-start no-wrap gap-3"):
                with ui.element("div").classes("k-icon shrink-0").style(f"background:{background}; color:{colour}"):
                    ui.icon(icon).classes("text-2xl").mark(f"tile-icon-{key}")
                with ui.column().classes("gap-0 grow min-w-0"):
                    card_title(title, TILE_INFO.get(key), f"total-{key}", "text-sm k-muted")
                    ui.label(DASH if text is None else text).classes("text-xl font-semibold").mark(f"total-{key}")
                    if (share := notes.get(key)) is not None:
                        note = f"{format_percent(share * 100)} portfela"
                        ui.label(note).classes("text-xs k-muted").mark(f"total-{key}-note")


def _since_snapshot(change: SnapshotChange | None) -> None:
    """The change since the last Valuation Snapshot of an earlier day (issue #115), before tax whatever the toggle;
    nothing without one."""
    if change is None:
        return
    text = f"Od {format_day_time(change.since)}: {format_pln(change.total, signed=True)}"
    if change.percent is not None:
        text += f" ({format_percent(change.percent * 100, signed=True)})"
    text += (
        f", w tym rynek {format_pln(change.market, signed=True)}, "
        f"wpłaty netto {format_pln(change.net_deposits, signed=True)}"
    )
    ui.label(text).classes("text-sm text-gray-600").mark("since-snapshot")


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
    with ui.element("div").classes("w-full overflow-x-auto"):
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


def _first_steps() -> None:
    """A banner on a database with no Transaction yet, leading to Pomoc (issue #156)."""
    with ui.card().classes("w-full k-highlight").mark("first-steps"):
        with ui.row().classes("w-full items-center"):
            ui.icon("help", color="primary").classes("text-2xl")
            ui.label("Pierwszy raz? Zobacz, od czego zacząć: konto, instrumenty, transakcje.").classes("grow")
            help_button = ui.button("Pomoc", icon="arrow_forward", on_click=lambda: ui.navigate.to(HELP_PATH))
            help_button.props("flat no-caps").mark("first-steps-help")


def _prices_line(refresh: RefreshStatus | None, unpriced: int) -> None:
    """When prices were last refreshed and how many Instruments failed, as in the header; the Instruments without a
    price lead to their list in Ustawienia."""
    with ui.row().classes("items-center gap-4 text-sm").mark("dashboard-prices"):
        ui.label(refresh_summary(refresh)).classes("text-negative" if refresh and refresh.failures else "text-gray-600")
        if unpriced:
            text = format_count(unpriced, "instrument bez wyceny", "instrumenty bez wyceny", "instrumentów bez wyceny")
            ui.link(text, "/ustawienia")
