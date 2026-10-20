"""The Dashboard's 9 charts from the sheet (issue #73, spec section 5) and its profit-by-source waterfall (issue
#89), drawn with ECharts.

Every chart follows the View Scope and the period: today's currency exposure, allocation and Account values, the
Dividends of the period by year, and from History the class shares over time, value vs Net Deposits, profit, XIRR and
drawdown. The waterfall is the result since the first Transaction, as in the tiles. Amounts go to ECharts as PLN
rounded to the grosz and shares as percent; ECharts formats them in Polish.
"""

import copy
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from nicegui import ui
from nicegui.events import EChartPointClickEventArguments

from financial_app.domain.charts import (
    Grouping,
    class_shares,
    dividends_by_year,
    profit_series,
    value_series,
    xirr_series,
)
from financial_app.domain.dashboard import Dashboard, Totals
from financial_app.domain.formatting import currency_unit, format_date
from financial_app.domain.metrics import drawdowns
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.prices import Quote
from financial_app.domain.profit_sources import ProfitSources
from financial_app.domain.transactions import TransactionDraft
from financial_app.ui.info import card_title
from financial_app.ui.theme import LABEL_COLOURS, LINE_COLOURS, current_theme, echart

# ECharts formats in the browser, so its tooltips and axes write numbers as domain/formatting.py does: a decimal comma,
# non-breaking spaces between thousands (4-digit numbers too) and before "zł" and "%"
_NBSP = "\N{NO-BREAK SPACE}"


def _formatter(unit: str, decimals: int = 2) -> str:
    """A tooltip's value with 2 to ``decimals`` decimal places followed by ``unit``; "—" without one."""
    return (
        "value => value == null ? '—' : new Intl.NumberFormat('pl-PL', {minimumFractionDigits: 2, "
        f"maximumFractionDigits: {decimals}, useGrouping: 'always'}})"
        rf".format(value).replace(/\s/g, '{_NBSP}') + '{_NBSP}{unit}'"
    )


PLN_FORMATTER = _formatter("zł")
_PERCENT = _formatter("%")
_AXIS_PLN = (
    "value => new Intl.NumberFormat('pl-PL', {maximumFractionDigits: 0, useGrouping: 'always'})"
    rf".format(value).replace(/\s/g, '{_NBSP}')"
)
_AXIS_PERCENT = f"value => value + '{_NBSP}%'"
# A waterfall bar is a rectangle from the running total before it (value[1]) to after it (value[2]), its signed
# change (value[3]) in whole złoty above it, in the Theme's ``{label}`` colour
_WATERFALL_CHANGE = (
    "value => new Intl.NumberFormat('pl-PL', {maximumFractionDigits: 0, useGrouping: 'always',"
    rf" signDisplay: 'exceptZero'}}).format(value).replace(/\s/g, '{_NBSP}').replace('\u2212', '-') + '{_NBSP}zł'"
)
_WATERFALL_BAR = f"""(params, api) => {{
    const top = api.coord([api.value(0), Math.max(api.value(1), api.value(2))]);
    const bottom = api.coord([api.value(0), Math.min(api.value(1), api.value(2))]);
    const width = api.size([1, 0])[0] * 0.6;
    const change = {_WATERFALL_CHANGE};
    return {{type: 'group', children: [
        {{type: 'rect', shape: {{x: top[0] - width / 2, y: top[1], width: width, height: bottom[1] - top[1]}},
         style: {{fill: api.visual('color')}}}},
        {{type: 'text', style: {{text: change(api.value(3)), x: top[0], y: top[1] - 4, align: 'center',
         verticalAlign: 'bottom', fill: '{{label}}', fontSize: 11}}}},
    ]}};
}}"""
_GAIN, _LOSS, _RESULT = "#2e7d32", "#c62828", "#3f51b5"

# What each Dashboard chart shows and how to read it, behind the "i" in its card's corner
# The charts drawn from History, which wait for it
HISTORY_CHARTS = ("class-shares", "value", "profit", "xirr", "drawdown")
CHART_INFO = {
    "waterfall": (
        "Skąd wziął się Twój wynik od pierwszej transakcji. Każdy słupek zaczyna się tam, gdzie skończył się "
        "poprzedni: zielony podnosi wynik, czerwony go obniża, a niebieski „Wynik” to ich suma.\n\n"
        "Efekt ceny: zmiana kursów instrumentów w ich walucie, przed prowizjami.\n"
        "Efekt walutowy: ile dała zmiana kursu walut, w tym na gotówce w walucie obcej.\n"
        "Dywidendy i Odsetki: wypłaty brutto.\n"
        "Prowizje i koszty: prowizje, opłaty za przewalutowanie i inne koszty.\n"
        "Podatki: podatek pobrany u źródła i przy przedterminowym wykupie obligacji; z „Po podatku” także "
        "szacowany podatek od niezrealizowanych zysków.\n\n"
        "Kwota nad słupkiem to jego zmiana w złotych."
    ),
    "dividends": (
        "Dywidendy i odsetki otrzymane w każdym roku wybranego okresu, z podziałem na konta (kolory słupka). "
        "Rosnące słupki oznaczają rosnący dochód pasywny."
    ),
    "currencies": (
        "W jakich walutach jest Twój majątek dziś: pozycje według waluty notowania i gotówka, przeliczone na złote. "
        "Duży udział walut obcych oznacza, że kurs złotego mocno wpływa na wynik (efekt walutowy)."
    ),
    "accounts": (
        "Wartość każdego konta dziś, podzielona na otwarte pozycje i gotówkę. Długi odcinek gotówki oznacza "
        "pieniądze, które czekają na zainwestowanie."
    ),
    "allocation": (
        "Dzisiejszy udział każdej klasy aktywów w wartości portfela (z gotówką). Jeśli ustawisz cele w zakładce "
        "Strategie inwestycyjne, obok udziału pojawi się słupek „Cel”; różnica między nimi pokazuje, co warto "
        "dokupić przy rebalansowaniu."
    ),
    "class-shares": (
        "Jak zmieniał się udział klas aktywów w portfelu w kolejnych miesiącach, kwartałach, półroczach lub latach "
        "(przełącznik nad wykresem). Każdy słupek sumuje się do 100 %."
    ),
    "value": (
        "Wartość konta (pozycje i gotówka) na tle wpłat netto, czyli wpłat pomniejszonych o wypłaty. Gdy linia "
        "wartości jest nad linią wpłat, jesteś na plusie; odległość między nimi to zysk lub strata."
    ),
    "profit": (
        "Zysk lub strata każdego dnia: wartość konta minus wpłaty netto. Powyżej zera jesteś na plusie. Skoki "
        "wynikają ze zmian cen i kursów, a nie z samych wpłat, bo te są odjęte."
    ),
    "xirr": (
        "XIRR to roczna stopa zwrotu z uwzględnieniem terminów i kwot Twoich wpłat i wypłat, jak oprocentowanie "
        "lokaty dające ten sam wynik. Punkt na wykresie to XIRR od początku okresu do tego dnia; na krótkim "
        "odcinku czasu potrafi mocno skakać."
    ),
    "drawdown": (
        "Obsunięcie: o ile procent stopa zwrotu (TWR, bez wpływu wpłat i wypłat) jest poniżej swojego najwyższego "
        "punktu w okresie. 0 % oznacza nowy szczyt; najniższy punkt to największy spadek, jaki portfel przeszedł."
    ),
}


def dashboard_charts(
    board: Dashboard,
    transactions: Sequence[TransactionDraft],
    account_names: Mapping[int, str],
    history: Sequence[DayValue] | None,
    account_id: int | None,
    period: tuple[date, date],
    targets: Mapping[str, Decimal] | None = None,
    sources: ProfitSources | None = None,
    shows: Callable[[str], bool] = lambda key: True,
) -> None:
    """The charts ``shows`` shows by their ``chart-`` key, in a grid of cards; those from History wait for it,
    ``None`` while it is computed. ``targets`` are the View Scope's Allocation Targets (percent by Asset Class name),
    shown beside the allocation; ``sources`` the result by source the waterfall shows (the board's, unless after
    tax)."""
    first, last = period
    with (
        ui.element("div")
        .classes("grid w-full gap-4")
        .style("grid-template-columns: repeat(auto-fill, minmax(26rem, 1fr))")
        .mark("dashboard-charts")
    ):
        if shows("chart-waterfall"):
            _card("Wynik według źródeł", "waterfall", _waterfall(sources or board.sources))
        if shows("chart-dividends"):
            _card(
                "Dywidendy i odsetki w latach",
                "dividends",
                _dividends(transactions, account_names, first, last, account_id),
            )
        if shows("chart-currencies"):
            _card("Waluty w portfelu", "currencies", _currencies(board))
        if shows("chart-accounts"):
            _card("Wartość kont", "accounts", _accounts(board))
        if shows("chart-allocation"):
            _card("Alokacja", "allocation", _allocation(board, targets or {}))
        if not any(shows(f"chart-{name}") for name in HISTORY_CHARTS):
            return
        if history is None:
            with ui.card().classes("w-full").mark("chart-history-pending"):
                ui.label("Wykresy historii: wyliczanie historii…").classes("k-muted")
            return
        if shows("chart-class-shares"):
            _class_shares_card(history, first, last, account_id)
        if shows("chart-value"):
            _card("Wartość konta vs wpłaty netto", "value", _value(history, first, last, account_id), timeline=True)
        if shows("chart-profit"):
            _card("Zysk / strata", "profit", _profit(history, first, last, account_id), timeline=True)
        if shows("chart-xirr"):
            _card("XIRR", "xirr", _xirr(history, first, last, account_id), timeline=True)
        if shows("chart-drawdown"):
            drawdown_chart(history, first, last, account_id)


def hero_value_chart(history: Sequence[DayValue], first: date, last: date, account_id: int | None) -> None:
    """The value over the period as a line over a fading area, in the Theme's colour, marked ``chart-hero`` (the
    Dashboard's main card, issue #174)."""
    colours = LINE_COLOURS[current_theme()]
    points = value_series(history, first, last, account_id)
    options = {
        "tooltip": {"trigger": "axis", ":valueFormatter": PLN_FORMATTER},
        "grid": {"containLabel": True, "left": 32, "right": 8, "top": 12, "bottom": 8},
        "xAxis": {
            "type": "category",
            "boundaryGap": False,
            "data": [format_date(point.day) for point in points],
            "axisTick": {"show": False},
        },
        "yAxis": {"type": "value", "scale": True, "position": "right", "axisLabel": {":formatter": _AXIS_PLN}},
        "series": [
            {
                "name": "Wartość portfela",
                "type": "line",
                "showSymbol": False,
                "data": [_pln(point.value) for point in points],
                "lineStyle": {"color": colours["value"], "width": 2},
                "itemStyle": {"color": colours["value"]},
                "areaStyle": {"color": _fading(colours["area"])},
            }
        ],
    }
    echart(options).classes("w-full h-64").mark("chart-hero")


def price_chart(quotes: Sequence[Quote], currency: str) -> None:
    """The closes in ``currency`` as a line over a fading area, in the Theme's colour, marked ``chart-price`` (the
    Instrument Card, issue #175)."""
    colours = LINE_COLOURS[current_theme()]
    options = {
        "tooltip": {"trigger": "axis", ":valueFormatter": _formatter(currency_unit(currency), decimals=4)},
        "grid": {"containLabel": True, "left": 8, "right": 8, "top": 12, "bottom": 8},
        "xAxis": {
            "type": "category",
            "boundaryGap": False,
            "data": [format_date(quote.day) for quote in quotes],
            "axisTick": {"show": False},
        },
        "yAxis": {"type": "value", "scale": True, "position": "right"},
        "series": [
            {
                "name": "Cena",
                "type": "line",
                "showSymbol": False,
                "data": [float(quote.price) for quote in quotes],
                "lineStyle": {"color": colours["value"], "width": 2},
                "itemStyle": {"color": colours["value"]},
                "areaStyle": {"color": _fading(colours["area"])},
            }
        ],
    }
    echart(options).classes("w-full h-72").mark("chart-price")


def sparkline(values: Sequence[Decimal], name: str) -> None:
    """A small line of ``values`` with no axes, green when it ends above where it starts, red below, marked
    ``sparkline-<name>`` (an Account's card)."""
    colours = LINE_COLOURS[current_theme()]
    colour = colours["gain"] if not values or values[-1] >= values[0] else colours["loss"]
    options = {
        "grid": {"left": 0, "right": 0, "top": 2, "bottom": 2},
        "xAxis": {"type": "category", "show": False, "boundaryGap": False},
        "yAxis": {"type": "value", "show": False, "scale": True},
        "series": [
            {
                "type": "line",
                "showSymbol": False,
                "silent": True,
                "data": [_pln(value) for value in values],
                "lineStyle": {"color": colour, "width": 1.5},
                "areaStyle": {"color": colour, "opacity": 0.12},
            }
        ],
    }
    echart(options).classes("w-28 h-10 shrink-0").mark(f"sparkline-{name}")


def _fading(colour: str) -> dict[str, Any]:
    """``colour`` at the top fading to nothing at the bottom."""
    stops = [{"offset": 0, "color": colour}, {"offset": 1, "color": "rgba(0,0,0,0)"}]
    return {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1, "colorStops": stops}


def drawdown_chart(
    history: Sequence[DayValue], first: date, last: date, account_id: int | None, name: str = "drawdown"
) -> None:
    """The drawdown of the TWR from the "from" day, in a card marked ``chart-<name>``; also on the Wyniki tab."""
    _card("Drawdown", name, _drawdown(history, first, last, account_id), CHART_INFO["drawdown"], timeline=True)


def pln_lines_chart(title: str, name: str, days: Sequence[date], series: Mapping[str, Sequence[Decimal]]) -> None:
    """Lines of PLN amounts by day in a card marked ``chart-<name>`` (the Benchmarki tab's, issue #91)."""
    amounts = {label: [_pln(amount) for amount in values] for label, values in series.items()}
    _card(title, name, _lines(days, amounts, PLN_FORMATTER, _AXIS_PLN), timeline=True)


def pln_bars_chart(
    title: str,
    name: str,
    categories: Sequence[str],
    series: Mapping[str, Sequence[Decimal]],
    line: tuple[str, Decimal] | None = None,
) -> None:
    """Stacked bars of PLN amounts by category in a card marked ``chart-<name>``, with ``line`` (its name and amount) a
    level marked across them (the Benchmarki and Dochód pasywny tabs', issues #91 and #93)."""
    bars: list[dict[str, Any]] = [
        {"name": label, "type": "bar", "stack": "total", "data": [_pln(amount) for amount in values]}
        for label, values in series.items()
    ]
    if line is not None and bars:
        label, level = line
        bars[0]["markLine"] = {"symbol": "none", "label": {"formatter": label}, "data": [{"yAxis": _pln(level)}]}
    options = {
        "tooltip": {"trigger": "axis", ":valueFormatter": PLN_FORMATTER},
        "legend": {"type": "scroll", "bottom": 0},
        "grid": {"containLabel": True, "bottom": 40},
        "xAxis": {"type": "category", "data": list(categories)},
        "yAxis": {"type": "value", "axisLabel": {":formatter": _AXIS_PLN}},
        "series": bars,
    }
    _card(title, name, options)


def _card(title: str, name: str, options: dict[str, Any], info: str | None = None, timeline: bool = False) -> None:
    """A chart in a card marked ``chart-<name>``, with an "i" (marked ``info-<name>``) showing ``info``, by default
    its ``CHART_INFO``, and the zoom button in its corner."""
    with ui.card().classes("relative w-full gap-1"):
        card_title(title, info or CHART_INFO.get(name), name)
        echart(options).classes("w-full h-72").mark(f"chart-{name}")
        zoom_button(title, name, options, timeline=timeline)


def zoom_button(
    title: str,
    name: str,
    options: dict[str, Any],
    on_point_click: Callable[[EChartPointClickEventArguments], None] | None = None,
    timeline: bool = False,
) -> None:
    """The button (marked ``zoom-<name>``) in its card's bottom right corner opening the chart in a dialog nearly
    the size of the window (issue #154); the dialog is built on the click and deleted once closed. A click on a
    point of the zoomed chart closes it before ``on_point_click``; a ``timeline`` (a chart over time) gets a slider
    and the mouse wheel to zoom into a part of its period."""

    def zoom() -> None:
        zoomed = copy.deepcopy(options)
        if timeline:
            # The slider sits above the legend at the bottom
            zoomed["dataZoom"] = [{"type": "inside"}, {"type": "slider", "bottom": 32}]
            zoomed["grid"] = {**zoomed.get("grid", {}), "bottom": 90}

        def clicked(event: EChartPointClickEventArguments) -> None:
            dialog.close()
            if on_point_click is not None:
                on_point_click(event)

        with ui.dialog(value=True) as dialog, ui.card().style("width: 95vw; max-width: 95vw; height: 90vh"):
            dialog.on_value_change(lambda event: None if event.value else dialog.delete())
            with ui.row().classes("w-full items-center"):
                ui.label(title).classes("text-lg font-medium")
                ui.space()
                ui.button(icon="close", on_click=dialog.close).props("flat round dense").mark("zoom-close")
            chart = echart(zoomed, on_point_click=clicked if on_point_click else None)
            chart.classes("w-full flex-1 min-h-0").mark(f"chart-{name}-zoomed")

    button = ui.button(icon="open_in_full", on_click=zoom).props("flat round dense size=sm color=grey-7")
    button.classes("absolute bottom-1 right-1").mark(f"zoom-{name}")
    button.tooltip("Powiększ wykres")


def _class_shares_card(history: Sequence[DayValue], first: date, last: date, account_id: int | None) -> None:
    """The class shares over time with the month / quarter / half-year / year switch, redrawn on its own."""

    @ui.refreshable
    def shown(grouping: Grouping) -> None:
        with ui.button_group().props("flat"):
            for choice in Grouping:
                button = ui.button(choice.label, on_click=lambda c=choice: shown.refresh(c)).props("no-caps dense")
                button.props("unelevated color=primary" if choice is grouping else "flat color=grey-8")
                button.classes("px-2").mark(f"grouping-{choice}")
        shares = class_shares(history, first, last, account_id, grouping)
        names = list(dict.fromkeys(name for share in shares for name in share.shares))
        options = {
            "tooltip": {"trigger": "axis", ":valueFormatter": _PERCENT},
            "legend": {"type": "scroll", "bottom": 0},
            "grid": {"containLabel": True, "bottom": 40},
            "xAxis": {"type": "category", "data": [share.label for share in shares]},
            "yAxis": {"type": "value", "max": 100, "axisLabel": {":formatter": _AXIS_PERCENT}},
            "series": [
                {
                    "name": name,
                    "type": "bar",
                    "stack": "classes",
                    "data": [_percent(share.shares.get(name, Decimal(0))) for share in shares],
                }
                for name in names
            ],
        }
        echart(options).classes("w-full h-72").mark("chart-class-shares")
        zoom_button("Udział aktywów w czasie", "class-shares", options, timeline=True)

    with ui.card().classes("relative w-full gap-1"):
        card_title("Udział aktywów w czasie", CHART_INFO["class-shares"], "class-shares")
        shown(Grouping.MONTH)


def _dividends(
    transactions: Sequence[TransactionDraft],
    account_names: Mapping[int, str],
    first: date,
    last: date,
    account_id: int | None,
) -> dict[str, Any]:
    years = dividends_by_year(transactions, first, last, account_id)
    accounts = sorted({a for paid in years.values() for a in paid}, key=lambda a: account_names.get(a, ""))
    return {
        "tooltip": {"trigger": "axis", ":valueFormatter": PLN_FORMATTER},
        "legend": {"type": "scroll", "bottom": 0},
        "grid": {"containLabel": True, "bottom": 40},
        "xAxis": {"type": "category", "data": [str(year) for year in years]},
        "yAxis": {"type": "value", "axisLabel": {":formatter": _AXIS_PLN}},
        "series": [
            {
                "name": account_names.get(account, ""),
                "type": "bar",
                "stack": "dividends",
                "data": [_pln(paid.get(account, Decimal(0))) for paid in years.values()],
            }
            for account in accounts
        ],
    }


def _currencies(board: Dashboard) -> dict[str, Any]:
    return {
        "tooltip": {"trigger": "item", ":valueFormatter": PLN_FORMATTER},
        "legend": {"type": "scroll", "bottom": 0},
        "series": [
            {
                "type": "pie",
                "radius": ["45%", "70%"],
                "data": [
                    {"name": share.currency, "value": _pln(share.value)} for share in board.currencies if share.value
                ],
            }
        ],
    }


def _accounts(board: Dashboard) -> dict[str, Any]:
    """Each Account's value as its open Positions and cash, the largest at the top."""
    rows = sorted(board.accounts, key=lambda row: row.totals.value)
    parts: tuple[tuple[str, Callable[[Totals], Decimal]], ...] = (
        ("Otwarte pozycje", lambda totals: totals.open_positions),
        ("Gotówka", lambda totals: totals.cash),
    )
    return {
        "tooltip": {"trigger": "axis", ":valueFormatter": PLN_FORMATTER},
        "legend": {"bottom": 0},
        "grid": {"containLabel": True, "bottom": 40},
        "xAxis": {"type": "value", "axisLabel": {":formatter": _AXIS_PLN}},
        "yAxis": {"type": "category", "data": [row.account.name for row in rows]},
        "series": [
            {"name": name, "type": "bar", "stack": "value", "data": [_pln(part(row.totals)) for row in rows]}
            for name, part in parts
        ],
    }


def _allocation(board: Dashboard, targets: Mapping[str, Decimal]) -> dict[str, Any]:
    """Today's share of each Asset Class, the largest at the top, beside its Allocation Target if it has one."""
    shares = {share.asset_class: share.share for share in board.classes}
    names = sorted({*shares, *targets}, key=lambda name: shares.get(name, Decimal(0)))
    series: list[dict[str, Any]] = [
        {"name": "Udział", "type": "bar", "data": [_percent(shares.get(name, Decimal(0))) for name in names]}
    ]
    if targets:
        target_data = [None if name not in targets else float(targets[name]) for name in names]
        series.append({"name": "Cel", "type": "bar", "data": target_data})
    return {
        "tooltip": {"trigger": "axis", ":valueFormatter": _PERCENT},
        "grid": {"containLabel": True},
        "xAxis": {"type": "value", "axisLabel": {":formatter": _AXIS_PERCENT}},
        "yAxis": {"type": "category", "data": names},
        "series": series,
    }


def _waterfall(sources: ProfitSources) -> dict[str, Any]:
    """Each source's change from the running total before it, then the result from zero."""
    steps = (
        ("Efekt ceny", sources.price),
        ("Efekt walutowy", sources.fx),
        ("Dywidendy", sources.dividends),
        ("Odsetki", sources.interest),
        ("Prowizje i koszty", sources.costs),
        ("Podatki", sources.taxes),
    )
    bars = []
    running = Decimal(0)
    for index, (name, change) in enumerate(steps):
        colour = _GAIN if change >= 0 else _LOSS
        bars.append(_bar(index, name, running, running + change, change, colour))
        running += change
    bars.append(_bar(len(steps), "Wynik", Decimal(0), running, running, _RESULT))
    tooltip = f"p => {{ const pln = {PLN_FORMATTER}; return p.name + ': ' + pln(p.value[3]); }}"
    return {
        "tooltip": {"trigger": "item", ":formatter": tooltip},
        "grid": {"containLabel": True},
        "xAxis": {
            "type": "category",
            "data": [bar["name"] for bar in bars],
            "axisLabel": {"interval": 0, "rotate": 35},
        },
        "yAxis": {"type": "value", "axisLabel": {":formatter": _AXIS_PLN}},
        "series": [
            {
                "name": "Zmiana",
                "type": "custom",
                ":renderItem": _WATERFALL_BAR.replace("{label}", LABEL_COLOURS[current_theme()]),
                "encode": {"x": 0, "y": [1, 2]},
                "data": bars,
            }
        ],
    }


def _bar(index: int, name: str, start: Decimal, end: Decimal, change: Decimal, colour: str) -> dict[str, Any]:
    return {"name": name, "value": [index, _pln(start), _pln(end), _pln(change)], "itemStyle": {"color": colour}}


def _value(history: Sequence[DayValue], first: date, last: date, account_id: int | None) -> dict[str, Any]:
    points = value_series(history, first, last, account_id)
    return _lines(
        [point.day for point in points],
        {
            "Wartość konta": [_pln(point.value) for point in points],
            "Wpłaty netto": [_pln(point.net_deposits) for point in points],
        },
        PLN_FORMATTER,
        _AXIS_PLN,
    )


def _profit(history: Sequence[DayValue], first: date, last: date, account_id: int | None) -> dict[str, Any]:
    points = profit_series(history, first, last, account_id)
    return _lines([day for day, _ in points], {"Zysk / strata": [_pln(p) for _, p in points]}, PLN_FORMATTER, _AXIS_PLN)


def _xirr(history: Sequence[DayValue], first: date, last: date, account_id: int | None) -> dict[str, Any]:
    points = xirr_series(history, first, last, account_id)
    rates = [None if rate is None else _percent(rate) for _, rate in points]
    return _lines([day for day, _ in points], {"XIRR": rates}, _PERCENT, _AXIS_PERCENT)


def _drawdown(history: Sequence[DayValue], first: date, last: date, account_id: int | None) -> dict[str, Any]:
    points = drawdowns(history, first, last, account_id)
    options = _lines(
        [day for day, _ in points], {"Drawdown": [_percent(d) for _, d in points]}, _PERCENT, _AXIS_PERCENT
    )
    options["series"][0]["areaStyle"] = {}
    return options


def _lines(
    days: Sequence[date], series: Mapping[str, Sequence[float | None]], tooltip: str, axis: str
) -> dict[str, Any]:
    return {
        "tooltip": {"trigger": "axis", ":valueFormatter": tooltip},
        "legend": {"bottom": 0},
        "grid": {"containLabel": True, "bottom": 40},
        "xAxis": {"type": "category", "data": [format_date(day) for day in days]},
        "yAxis": {"type": "value", "scale": True, "axisLabel": {":formatter": axis}},
        "series": [
            {"name": name, "type": "line", "showSymbol": False, "connectNulls": True, "data": list(values)}
            for name, values in series.items()
        ],
    }


def _pln(amount: Decimal) -> float:
    return round(float(amount), 2)


def _percent(fraction: Decimal) -> float:
    return round(float(fraction * 100), 2)
