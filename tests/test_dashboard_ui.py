"""The Dashboard tab: totals, the Account table, currency exposure and the price status (issue #72, spec section 5),
with History computed in the test from the cache alone."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.prices import YAHOO
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes, list_instruments
from financial_app.persistence.quotes import save_refresh
from financial_app.persistence.transactions import add_transactions
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates
from financial_app.sources.portfolio_history import PortfolioHistory
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
TODAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 9, 0)

type Compute = Callable[..., Awaitable[list[DayValue]]]


def _pln(text: str) -> str:
    return text.replace(" ", NBSP) + f"{NBSP}zł"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """IKE: 1000 PLN in, 10 PZU bought at 50 with a 5 PLN commission, PZU now 60 (Manual Price); XTB: 3000 PLN in,
    its FX result excluded."""
    engine = init_db(tmp_path / "app.sqlite3")
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    xtb = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",), exclude_fx_result=True)).id
    shares = next(c for c in list_asset_classes(engine) if c.name == "Akcje polskie")
    pzu = add_instrument(engine, InstrumentDraft("PZU", shares.id, "PLN", manual_price=Decimal(60))).id
    add_transactions(
        engine,
        [
            TransactionDraft(ike, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(1000)),
            TransactionDraft(xtb, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(3000)),
            buy_or_sell(ike, date(2026, 8, 4), TransactionType.BUY, pzu, Decimal(10), Decimal(50), Decimal(5)),
        ],
    )
    return engine


async def _inline(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
    return function(*args)


def _shell(engine: Engine, compute: Compute = _inline) -> Callable[[], None]:
    quotes = QuoteHistory(engine, lambda url: "Brak danych", lambda: TODAY, lambda: NOW, lambda url: None)
    history = PortfolioHistory(engine, quotes, NbpRates(engine), lambda: TODAY, compute)
    return lambda: build_shell(engine, now=lambda: NOW, history=history)


async def _tile(user: User, key: str, text: str) -> None:
    await user.should_see(marker=f"total-{key}", content=text)


async def test_the_dashboard_shows_the_totals_of_the_whole_portfolio(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")

        await _tile(user, "net-deposits", _pln("4 000,00"))
        await _tile(user, "value", _pln("4 095,00"))
        await _tile(user, "open-positions", _pln("600,00"))
        await _tile(user, "cash", _pln("3 495,00"))
        await _tile(user, "unrealized", _pln("+95,00"))
        await _tile(user, "realized", _pln("+0,00"))
        await _tile(user, "dividends", _pln("0,00"))
        await _tile(user, "costs", _pln("5,00"))


async def test_xirr_runs_over_the_period_to_todays_value(engine: Engine) -> None:
    # 4000 PLN in on 3.08 is worth 4095 PLN on 12.10 (PZU at its Manual Price, which History does not know)
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")

        await _tile(user, "xirr", f"13,02{NBSP}%")


async def test_choosing_a_period_recomputes_xirr_from_its_first_day(engine: Engine) -> None:
    # 1M: History's 4000 PLN on 12.09 (PZU at cost) grows to 4095 PLN today
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await _tile(user, "xirr", f"13,02{NBSP}%")

        with user.scope(marker="period-selector"):
            user.find("1M").click()

        await _tile(user, "xirr", f"33,05{NBSP}%")


def _rows(user: User, marker: str) -> list[list[str]]:
    """The rows with ``marker`` top to bottom, each as its texts."""
    rows = sorted(user.find(marker=marker).elements, key=lambda element: element.id)
    return [[d.text for d in row.descendants() if isinstance(d, ui.label)] for row in rows]


async def test_the_account_table_has_a_row_per_account_with_its_fx_exclusion(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await _tile(user, "xirr", f"13,02{NBSP}%")
        user.find(marker="accounts-view-table").click()
        await user.should_see(marker="account-row")

        assert _rows(user, "account-row") == [
            [
                "IKE",
                _pln("1 000,00"),
                _pln("1 095,00"),
                _pln("600,00"),
                _pln("495,00"),
                _pln("+95,00"),
                _pln("+0,00"),
                f"60,52{NBSP}%",
                _pln("0,00"),
                _pln("5,00"),
                "",
            ],
            [
                "XTB",
                _pln("3 000,00"),
                _pln("3 000,00"),
                _pln("0,00"),
                _pln("3 000,00"),
                _pln("+0,00"),
                _pln("+0,00"),
                f"0,00{NBSP}%",
                _pln("0,00"),
                _pln("0,00"),
                "bez wyniku walutowego",
            ],
        ]


async def test_currency_exposure_lists_each_currency_with_its_share(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await user.should_see(marker="currency-row")

        assert _rows(user, "currency-row") == [["PLN", _pln("4 095,00"), f"100,00{NBSP}%"]]


async def test_an_account_scope_shows_only_that_accounts_totals_and_row(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await _tile(user, "xirr", f"13,02{NBSP}%")
        user.find(marker="view-scope").click()
        await user.should_see(marker="scope-menu")
        user.find(marker="scope-2").click()

        await _tile(user, "value", _pln("3 000,00"))
        await _tile(user, "net-deposits", _pln("3 000,00"))
        await _tile(user, "costs", _pln("0,00"))
        user.find(marker="accounts-view-table").click()
        await user.should_see(marker="account-row")
        assert [row[0] for row in _rows(user, "account-row")] == ["XTB"]


async def test_net_deposits_and_xirr_show_a_dash_while_history_loads(engine: Engine) -> None:
    computed = asyncio.Event()

    async def slow(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
        await computed.wait()
        return function(*args)

    async with user_simulation(_shell(engine, slow)) as user:
        await user.open("/")

        await _tile(user, "value", _pln("4 095,00"))
        await _tile(user, "net-deposits", "—")
        await _tile(user, "xirr", "—")
        computed.set()
        await _tile(user, "net-deposits", _pln("4 000,00"))


async def test_the_price_status_shows_the_last_refresh_its_errors_and_the_unpriced_instruments(engine: Engine) -> None:
    [pzu] = list_instruments(engine)
    save_refresh(engine, datetime(2026, 10, 12, 8, 0), {pzu.id: {YAHOO: "Brak danych"}}, succeeded=False)

    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await _tile(user, "xirr", f"13,02{NBSP}%")

        with user.scope(marker="dashboard-prices"):
            await user.should_see("Wyceny: 12.10.2026 08:00 · 1 błąd")
            await user.should_see("1 instrument bez wyceny")
            user.find("1 instrument bez wyceny").click()
        await user.should_see("Klasy aktywów")


async def test_the_main_card_shows_the_value_beside_the_period_and_the_value_chart(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        # The card is drawn again once History is computed, now with the chart
        await user.should_see(marker="chart-hero")

        with user.scope(marker="dashboard-hero"):
            await user.should_see(marker="hero-value", content=_pln("4 095,00"))
            await user.should_see(marker="period-selector")
            await user.should_see(marker="chart-hero")


async def test_each_tile_has_its_icon_and_cash_and_costs_their_share_of_the_portfolio(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await _tile(user, "value", _pln("4 095,00"))

        for key in ("net-deposits", "value", "cash", "xirr"):
            await user.should_see(marker=f"tile-icon-{key}")
        await user.should_see(marker="total-cash-note", content=f"85,35{NBSP}% portfela")
        await user.should_see(marker="total-costs-note", content=f"0,12{NBSP}% portfela")


async def test_accounts_show_as_cards_with_their_profit_and_the_table_one_click_away(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        await _tile(user, "xirr", f"13,02{NBSP}%")

        assert _rows(user, "account-card") == [
            ["IKE", _pln("1 095,00"), f"{_pln('+95,00')} (+9,50{NBSP}%)"],
            ["XTB", _pln("3 000,00"), f"{_pln('+0,00')} (+0,00{NBSP}%)"],
        ]
        await user.should_not_see(marker="account-row")

        user.find(marker="accounts-view-table").click()
        await user.should_see(marker="account-row")
        await user.should_not_see(marker="account-card")

        user.find(marker="accounts-view-cards").click()
        await user.should_see(marker="account-card")
