"""A chart card's zoom button opens the same chart in a dialog nearly the size of the window (issue #154)."""

import asyncio
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell, dividend
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import add_transactions
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates
from financial_app.sources.portfolio_history import PortfolioHistory
from financial_app.ui.shell import build_shell

TODAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 9, 0)
CHARTS = (
    "waterfall",
    "dividends",
    "currencies",
    "accounts",
    "allocation",
    "class-shares",
    "value",
    "profit",
    "xirr",
    "drawdown",
    "accounts-treemap",
)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """IKE: 1000 PLN in, 10 PZU at 50, a 20 PLN Dividend; XTB: 3000 PLN in. PZU is now 60 (Manual Price)."""
    engine = init_db(tmp_path / "app.sqlite3")
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    xtb = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id
    shares = next(c for c in list_asset_classes(engine) if c.name == "Akcje polskie")
    pzu = add_instrument(engine, InstrumentDraft("PZU", shares.id, "PLN", manual_price=Decimal(60))).id
    add_transactions(
        engine,
        [
            TransactionDraft(ike, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(1000)),
            TransactionDraft(xtb, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(3000)),
            buy_or_sell(ike, date(2026, 8, 4), TransactionType.BUY, pzu, Decimal(10), Decimal(50), Decimal(5)),
            dividend(ike, date(2026, 10, 1), Decimal(20), instrument_id=pzu),
        ],
    )
    return engine


async def _inline(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
    return function(*args)


def _shell(engine: Engine) -> Callable[[], None]:
    quotes = QuoteHistory(engine, lambda url: "Brak danych", lambda: TODAY, lambda: NOW, lambda url: None)
    history = PortfolioHistory(engine, quotes, NbpRates(engine), lambda: TODAY, _inline)
    return lambda: build_shell(engine, now=lambda: NOW, history=history)


def _options(user: User, marker: str) -> dict[str, Any]:
    [chart] = [element for element in user.find(marker=marker).elements if isinstance(element, ui.echart)]
    return chart.options


async def _until(check: Callable[[], Any]) -> None:
    for _ in range(50):
        if check():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition never held")


async def _opened(user: User) -> None:
    await user.open("/")
    await user.should_see(marker="chart-value")  # History computed


async def test_each_dashboard_chart_opens_zoomed_with_the_same_data(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await _opened(user)

        for name in CHARTS:
            user.find(marker=f"zoom-{name}").click()

            await user.should_see(marker=f"chart-{name}-zoomed")
            assert _options(user, f"chart-{name}-zoomed")["series"] == _options(user, f"chart-{name}")["series"], name
            user.find(marker="zoom-close").click()
            await user.should_not_see(marker=f"chart-{name}-zoomed")


async def test_clicking_an_account_in_the_zoomed_treemap_switches_the_view_scope_and_closes_it(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await _opened(user)
        user.find(marker="zoom-accounts-treemap").click()
        await user.should_see(marker="chart-accounts-treemap-zoomed")

        args = {"componentType": "series", "seriesType": "treemap", "seriesIndex": 0, "seriesName": "Konta"}
        args |= {"name": "XTB", "dataIndex": 1, "data": {}, "value": 3000.0}
        user.find(marker="chart-accounts-treemap-zoomed").trigger("componentClick", args)

        await _until(lambda: user.find(marker="view-scope").elements.pop().props["label"] == "XTB")
        await user.should_not_see(marker="chart-accounts-treemap-zoomed")


async def test_the_zoomed_class_shares_follow_the_chosen_grouping(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await _opened(user)
        user.find(marker="grouping-quarter").click()
        await _until(lambda: _options(user, "chart-class-shares")["xAxis"]["data"] == ["III kw. 2026", "IV kw. 2026"])

        user.find(marker="zoom-class-shares").click()

        await user.should_see(marker="chart-class-shares-zoomed")
        assert _options(user, "chart-class-shares-zoomed")["xAxis"]["data"] == ["III kw. 2026", "IV kw. 2026"]


async def _zoomed(user: User, name: str) -> dict[str, Any]:
    user.find(marker=f"zoom-{name}").click()
    await user.should_see(marker=f"chart-{name}-zoomed")
    options = _options(user, f"chart-{name}-zoomed")
    user.find(marker="zoom-close").click()
    await user.should_not_see(marker=f"chart-{name}-zoomed")
    return options


async def test_zoomed_charts_over_time_get_a_period_slider_and_the_others_do_not(engine: Engine) -> None:
    timelines = {"class-shares", "value", "profit", "xirr", "drawdown"}
    async with user_simulation(_shell(engine)) as user:
        await _opened(user)

        for name in CHARTS:
            options = await _zoomed(user, name)
            assert ("dataZoom" in options) == (name in timelines), name
        assert "dataZoom" not in _options(user, "chart-value")  # the card keeps its chart as it was

        await user.open("/benchmarki")
        await user.should_see(marker="chart-benchmarks-history")
        assert "dataZoom" in await _zoomed(user, "benchmarks-history")
        assert "dataZoom" not in await _zoomed(user, "benchmarks-values")
