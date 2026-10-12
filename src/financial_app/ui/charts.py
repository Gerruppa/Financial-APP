"""The Dashboard's 9 charts from the sheet (issue #73, spec section 5), drawn with ECharts.

Every chart follows the View Scope and the period: today's currency exposure, allocation and Account values, the
Dividends of the period by year, and from History the class shares over time, value vs Net Deposits, profit, XIRR and
drawdown. Amounts go to ECharts as PLN rounded to the grosz and shares as percent; ECharts formats them in Polish.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from nicegui import ui

from financial_app.domain.charts import (
    Grouping,
    class_shares,
    dividends_by_year,
    profit_series,
    value_series,
    xirr_series,
)
from financial_app.domain.dashboard import Dashboard, Totals
from financial_app.domain.formatting import format_date
from financial_app.domain.metrics import drawdowns
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.transactions import TransactionDraft

# ECharts formats in the browser, so its tooltips and axes write numbers as domain/formatting.py does: a decimal comma,
# non-breaking spaces between thousands (4-digit numbers too) and before "zł" and "%"
_NBSP = "\N{NO-BREAK SPACE}"
_DECIMALS = "minimumFractionDigits: 2, maximumFractionDigits: 2"
_PLN = (
    f"value => value == null ? '—' : new Intl.NumberFormat('pl-PL', {{{_DECIMALS}, useGrouping: 'always'}})"
    rf".format(value).replace(/\s/g, '{_NBSP}') + '{_NBSP}zł'"
)
_PERCENT = (
    f"value => value == null ? '—' : new Intl.NumberFormat('pl-PL', {{{_DECIMALS}, useGrouping: 'always'}})"
    rf".format(value).replace(/\s/g, '{_NBSP}') + '{_NBSP}%'"
)
_AXIS_PLN = (
    "value => new Intl.NumberFormat('pl-PL', {maximumFractionDigits: 0, useGrouping: 'always'})"
    rf".format(value).replace(/\s/g, '{_NBSP}')"
)
_AXIS_PERCENT = f"value => value + '{_NBSP}%'"


def dashboard_charts(
    board: Dashboard,
    transactions: Sequence[TransactionDraft],
    account_names: Mapping[int, str],
    history: Sequence[DayValue] | None,
    account_id: int | None,
    period: tuple[date, date],
) -> None:
    """The charts in a grid of cards; those from History wait for it, ``None`` while it is computed."""
    first, last = period
    with (
        ui.element("div")
        .classes("grid w-full gap-4")
        .style("grid-template-columns: repeat(auto-fill, minmax(26rem, 1fr))")
        .mark("dashboard-charts")
    ):
        _card(
            "Dywidendy i odsetki w latach",
            "dividends",
            _dividends(transactions, account_names, first, last, account_id),
        )
        _card("Waluty w portfelu", "currencies", _currencies(board))
        _card("Wartość kont", "accounts", _accounts(board))
        _card("Alokacja", "allocation", _allocation(board))
        if history is None:
            with ui.card().classes("w-full").mark("chart-history-pending"):
                ui.label("Wykresy historii: wyliczanie historii…").classes("text-gray-500")
            return
        _class_shares_card(history, first, last, account_id)
        _card("Wartość konta vs wpłaty netto", "value", _value(history, first, last, account_id))
        _card("Zysk / strata", "profit", _profit(history, first, last, account_id))
        _card("XIRR", "xirr", _xirr(history, first, last, account_id))
        _card("Drawdown", "drawdown", _drawdown(history, first, last, account_id))


def _card(title: str, name: str, options: dict[str, Any]) -> None:
    with ui.card().classes("w-full gap-1"):
        ui.label(title).classes("text-lg font-medium")
        ui.echart(options).classes("w-full h-72").mark(f"chart-{name}")


def _class_shares_card(history: Sequence[DayValue], first: date, last: date, account_id: int | None) -> None:
    """The class shares over time with the month / quarter / half-year / year switch, redrawn on its own."""

    @ui.refreshable
    def shown(grouping: Grouping) -> None:
        with ui.button_group().props("flat"):
            for choice in Grouping:
                button = ui.button(choice.label, on_click=lambda c=choice: shown.refresh(c)).props("no-caps dense")
                button.props("unelevated color=indigo" if choice is grouping else "flat color=grey-8")
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
        ui.echart(options).classes("w-full h-72").mark("chart-class-shares")

    with ui.card().classes("w-full gap-1"):
        ui.label("Udział aktywów w czasie").classes("text-lg font-medium")
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
        "tooltip": {"trigger": "axis", ":valueFormatter": _PLN},
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
        "tooltip": {"trigger": "item", ":valueFormatter": _PLN},
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
        "tooltip": {"trigger": "axis", ":valueFormatter": _PLN},
        "legend": {"bottom": 0},
        "grid": {"containLabel": True, "bottom": 40},
        "xAxis": {"type": "value", "axisLabel": {":formatter": _AXIS_PLN}},
        "yAxis": {"type": "category", "data": [row.account.name for row in rows]},
        "series": [
            {"name": name, "type": "bar", "stack": "value", "data": [_pln(part(row.totals)) for row in rows]}
            for name, part in parts
        ],
    }


def _allocation(board: Dashboard) -> dict[str, Any]:
    """Today's share of each Asset Class, the largest at the top (targets come with Investment Strategies)."""
    classes = sorted(board.classes, key=lambda share: share.share)
    return {
        "tooltip": {"trigger": "axis", ":valueFormatter": _PERCENT},
        "grid": {"containLabel": True},
        "xAxis": {"type": "value", "axisLabel": {":formatter": _AXIS_PERCENT}},
        "yAxis": {"type": "category", "data": [share.asset_class for share in classes]},
        "series": [{"name": "Udział", "type": "bar", "data": [_percent(share.share) for share in classes]}],
    }


def _value(history: Sequence[DayValue], first: date, last: date, account_id: int | None) -> dict[str, Any]:
    points = value_series(history, first, last, account_id)
    return _lines(
        [point.day for point in points],
        {
            "Wartość konta": [_pln(point.value) for point in points],
            "Wpłaty netto": [_pln(point.net_deposits) for point in points],
        },
        _PLN,
        _AXIS_PLN,
    )


def _profit(history: Sequence[DayValue], first: date, last: date, account_id: int | None) -> dict[str, Any]:
    points = profit_series(history, first, last, account_id)
    return _lines([day for day, _ in points], {"Zysk / strata": [_pln(p) for _, p in points]}, _PLN, _AXIS_PLN)


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
