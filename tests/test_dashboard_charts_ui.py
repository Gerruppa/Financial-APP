"""The Dashboard's 9 charts (issue #73, spec section 5): each follows the View Scope and the period, with History
computed in the test from the cache alone."""

import asyncio
from collections.abc import Awaitable, Callable
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
CHARTS = ("dividends", "currencies", "class-shares", "accounts", "allocation", "value", "profit", "xirr", "drawdown")

type Compute = Callable[..., Awaitable[list[DayValue]]]


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """IKE: 1000 PLN in on 3.08, 10 PZU bought at 50 with a 5 PLN commission, PZU now 60 (Manual Price), a 20 PLN
    Dividend on 1.10; XTB: 3000 PLN in on 3.08. History has no PZU price, so it values PZU at cost."""
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


def _shell(engine: Engine, compute: Compute = _inline) -> Callable[[], None]:
    quotes = QuoteHistory(engine, lambda url: "Brak danych", lambda: TODAY, lambda: NOW, lambda url: None)
    history = PortfolioHistory(engine, quotes, NbpRates(engine), lambda: TODAY, compute)
    return lambda: build_shell(engine, now=lambda: NOW, history=history)


def _options(user: User, name: str) -> dict[str, Any]:
    [chart] = [element for element in user.find(marker=f"chart-{name}").elements if isinstance(element, ui.echart)]
    return chart.options


async def _until(user: User, name: str, check: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    """The chart's options once ``check`` holds for them (a click redraws it in the background)."""
    for _ in range(50):
        options = _options(user, name)
        if check(options):
            return options
        await asyncio.sleep(0.02)
    raise AssertionError(f"chart-{name}: {options}")


async def _drawn(user: User) -> None:
    """Wait until History is computed and its charts drawn."""
    await user.should_see(marker="chart-value")


async def test_the_dashboard_draws_the_nine_charts_of_the_sheet(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await _drawn(user)

        for name in CHARTS:
            assert _options(user, name)["series"], name


async def test_value_and_profit_follow_history_over_the_period(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await _drawn(user)
        with user.scope(marker="period-selector"):
            user.find("1M").click()

        value = await _until(user, "value", lambda options: options["xAxis"]["data"][0] == "12.09.2026")
        assert [series["name"] for series in value["series"]] == ["Wartość konta", "Wpłaty netto"]
        # 1.10: the 20 PLN Dividend adds to the value, not to Net Deposits
        assert value["series"][0]["data"][-1] == 4020.0
        assert value["series"][1]["data"][-1] == 4000.0
        assert _options(user, "profit")["series"][0]["data"][-1] == 20.0


async def test_the_currency_doughnut_and_the_allocation_show_todays_values(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await _drawn(user)

        assert _options(user, "currencies")["series"][0]["data"] == [{"name": "PLN", "value": 4115.0}]
        allocation = _options(user, "allocation")
        assert allocation["yAxis"]["data"] == ["Akcje polskie", "Gotówka"]
        assert allocation["series"][0]["data"] == [14.58, 85.42]


async def test_dividends_are_stacked_by_year_per_account(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await _drawn(user)

        dividends = _options(user, "dividends")
        assert dividends["xAxis"]["data"] == ["2026"]
        assert [(series["name"], series["data"]) for series in dividends["series"]] == [("IKE", [20.0])]


async def test_the_class_share_chart_switches_between_month_quarter_half_year_and_year(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await _drawn(user)
        assert _options(user, "class-shares")["xAxis"]["data"] == ["08.2026", "09.2026", "10.2026"]

        user.find(marker="grouping-quarter").click()

        shares = await _until(
            user, "class-shares", lambda options: options["xAxis"]["data"] == ["III kw. 2026", "IV kw. 2026"]
        )
        assert {series["name"] for series in shares["series"]} == {"Gotówka", "Akcje polskie"}


async def test_an_account_scope_charts_only_that_account(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await _drawn(user)
        user.find(marker="view-scope").click()
        await user.should_see(marker="scope-menu")
        user.find(marker="scope-2").click()

        await _until(user, "accounts", lambda options: options["yAxis"]["data"] == ["XTB"])
        assert _options(user, "dividends")["series"] == []
        assert _options(user, "value")["series"][0]["data"][-1] == 3000.0


async def test_history_charts_wait_for_history_to_be_computed(engine: Engine) -> None:
    computed = asyncio.Event()

    async def slow(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
        await computed.wait()
        return function(*args)

    async with user_simulation(_shell(engine, slow)) as user:
        await user.open("/")

        await user.should_see(marker="chart-currencies")
        await user.should_see(marker="chart-history-pending")
        computed.set()
        await _drawn(user)
