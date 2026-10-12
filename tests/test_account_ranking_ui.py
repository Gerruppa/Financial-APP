"""The Total Dashboard's Accounts treemap and Account ranking, the profit-by-source waterfall and the "po podatku"
toggle (issue #89, spec section 5)."""

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


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """IKE (an IKE): 1000 PLN in, 10 PZU at 50 with a 5 PLN commission, a 20 PLN Dividend less 3,80 tax; XTB
    (Regular): 3000 PLN in, 20 PZU at 50 with a 10 PLN commission. PZU is now 60 (Manual Price)."""
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
            buy_or_sell(xtb, date(2026, 8, 4), TransactionType.BUY, pzu, Decimal(20), Decimal(50), Decimal(10)),
            dividend(ike, date(2026, 10, 1), Decimal(20), Decimal("3.80"), instrument_id=pzu),
        ],
    )
    return engine


async def _inline(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
    return function(*args)


def _shell(engine: Engine) -> Callable[[], None]:
    quotes = QuoteHistory(engine, lambda url: "Brak danych", lambda: TODAY, lambda: NOW, lambda url: None)
    history = PortfolioHistory(engine, quotes, NbpRates(engine), lambda: TODAY, _inline)
    return lambda: build_shell(engine, now=lambda: NOW, history=history)


def _chart(user: User, name: str) -> ui.echart:
    [chart] = [element for element in user.find(marker=f"chart-{name}").elements if isinstance(element, ui.echart)]
    return chart


def _ranking(user: User) -> list[list[str]]:
    """The ranking's rows top to bottom, each as its cells' texts (``find`` gives a set, so walk the card)."""
    [card] = user.find(marker="account-ranking").elements
    rows = [element for element in card.descendants() if "ranking-row" in element._markers]
    return [[label.text for label in row.descendants() if isinstance(label, ui.label)] for row in rows]


def _changes(options: dict[str, Any]) -> list[float]:
    """Each waterfall bar's signed change; a bar spans from the running total before it to after it."""
    [series] = options["series"]
    return [item["value"][3] for item in series["data"]]


async def _until(check: Callable[[], Any]) -> None:
    for _ in range(50):
        if check():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition never held")


async def _opened(user: User) -> None:
    await user.open("/")
    await user.should_see(marker="chart-value")  # History computed


async def test_the_total_dashboard_draws_a_treemap_tile_per_account_sized_by_value(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await _opened(user)

        [series] = _chart(user, "accounts-treemap").options["series"]
        assert [(tile["name"], tile["value"]) for tile in series["data"]] == [("XTB", 3190.0), ("IKE", 1111.2)]


async def test_clicking_a_treemap_tile_switches_the_view_scope_to_that_account(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await _opened(user)

        args = {"componentType": "series", "seriesType": "treemap", "seriesIndex": 0, "seriesName": "Konta"}
        args |= {"name": "XTB", "dataIndex": 1, "data": {}, "value": 3190.0}
        user.find(marker="chart-accounts-treemap").trigger("componentClick", args)

        await _until(lambda: user.find(marker="view-scope").elements.pop().props["label"] == "XTB")
        await user.should_not_see(marker="chart-accounts-treemap")
        await user.should_not_see(marker="account-ranking")


async def test_the_ranking_lists_each_accounts_figures_and_marks_the_best_and_worst(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await _opened(user)

        # History values PZU at cost, so P&L is today's value less Net Deposits, as in the tiles
        rows = _ranking(user)
        assert [row[0] for row in rows] == ["XTB", "IKE"]
        assert rows[0][3:] == [
            "+190,00\N{NO-BREAK SPACE}zł",
            "3\N{NO-BREAK SPACE}000,00\N{NO-BREAK SPACE}zł",
            "10,00\N{NO-BREAK SPACE}zł",
        ]
        assert len(user.find(marker="ranking-best").elements) >= 1
        assert len(user.find(marker="ranking-worst").elements) >= 1


async def test_the_ranking_sorts_by_a_clicked_column_and_back(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await _opened(user)

        def shown(label: str, order: list[str]) -> bool:
            [button] = user.find(marker="ranking-sort-costs").elements
            return button.props.get("label") == label and [row[0] for row in _ranking(user)] == order

        # Each click redraws the table a moment later, so wait for its arrow before the next one
        await _until(lambda: shown("Prowizje i koszty", ["XTB", "IKE"]))  # P&L, highest first
        user.find(marker="ranking-sort-costs").click()
        await _until(lambda: shown("Prowizje i koszty ↓", ["XTB", "IKE"]))
        user.find(marker="ranking-sort-costs").click()
        await _until(lambda: shown("Prowizje i koszty ↑", ["IKE", "XTB"]))


async def test_the_waterfall_splits_the_result_by_source_in_every_scope(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await _opened(user)

        options = _chart(user, "waterfall").options
        assert options["xAxis"]["data"] == [
            "Efekt ceny",
            "Efekt walutowy",
            "Dywidendy",
            "Odsetki",
            "Prowizje i koszty",
            "Podatki",
            "Wynik",
        ]
        # Price +300 (30 PZU 50 → 60), Dividend 20, costs −15, tax −3,80: a result of 301,20
        assert _changes(options) == [300.0, 0.0, 20.0, 0.0, -15.0, -3.8, 301.2]

        user.find(marker="view-scope").click()
        await user.should_see(marker="scope-menu")
        user.find(marker="scope-1").click()
        await _until(lambda: user.find(marker="view-scope").elements.pop().props["label"] == "IKE")
        await user.should_see(marker="chart-waterfall")


async def test_after_tax_takes_the_estimated_belka_off_regular_accounts_results(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await _opened(user)
        await user.should_not_see(marker="total-estimated-tax")

        user.find(marker="after-tax").click()

        # XTB (Regular) gains 190 zł at the Tax cost: 36,10 zł; IKE pays nothing
        await user.should_see(marker="total-estimated-tax")
        await _until(lambda: _ranking(user)[0][3] == "+153,90\N{NO-BREAK SPACE}zł")
        assert _ranking(user)[1][3] == "+111,20\N{NO-BREAK SPACE}zł"
        await _until(lambda: _changes(_chart(user, "waterfall").options)[-2:] == [-39.9, 265.1])
