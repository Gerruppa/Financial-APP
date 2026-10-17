"""Valuation Snapshots in the window (issue #115, ADR-0008): a Successful Refresh is snapshotted once History is
computed, and the Dashboard shows the change since the newest snapshot of an earlier day."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.prices import YAHOO, PriceSourceError, Quote
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.domain.valuation_snapshots import Figures, ValuationSnapshot
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import add_transactions
from financial_app.persistence.valuation_snapshots import save_snapshot, snapshot_before
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates
from financial_app.sources.portfolio_history import PortfolioHistory
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
TODAY = date(2026, 10, 16)
NOW = datetime(2026, 10, 16, 18, 5)
TOMORROW = date(2026, 10, 17)

type Compute = Callable[..., Awaitable[list[DayValue]]]


class FakeYahoo:
    name = YAHOO

    def __init__(self, prices: dict[str, str]) -> None:
        self.prices = prices

    def new_refresh(self) -> None:
        pass

    def quote(self, symbol: str, currency: str) -> Quote:
        if symbol not in self.prices:
            raise PriceSourceError(f"Yahoo nie zna symbolu „{symbol}”.")
        return Quote(Decimal(self.prices[symbol]), currency, TODAY, YAHOO)


def _pln(text: str) -> str:
    return text.replace(" ", NBSP) + f"{NBSP}zł"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """IKE: 1000 PLN in, 10 PZU bought at 50 (Yahoo PZU.WA); XTB: 3000 PLN in."""
    engine = init_db(tmp_path / "app.sqlite3")
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    xtb = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id
    shares = next(c for c in list_asset_classes(engine) if c.name == "Akcje polskie")
    pzu = add_instrument(engine, InstrumentDraft("PZU", shares.id, "PLN", source_symbols={YAHOO: "PZU.WA"})).id
    add_transactions(
        engine,
        [
            TransactionDraft(ike, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(1000)),
            TransactionDraft(xtb, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(3000)),
            buy_or_sell(ike, date(2026, 8, 4), TransactionType.BUY, pzu, Decimal(10), Decimal(50)),
        ],
    )
    return engine


async def _inline(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
    return function(*args)


def _shell(engine: Engine, prices: dict[str, str], compute: Compute = _inline) -> Callable[[], None]:
    rates = NbpRates(engine, fetch=lambda url: None, today=lambda: TODAY)
    quotes = QuoteHistory(engine, lambda url: "Brak danych", lambda: TODAY, lambda: NOW, lambda url: None)
    history = PortfolioHistory(engine, quotes, rates, lambda: TODAY, compute)
    return lambda: build_shell(engine, rates, sources={YAHOO: FakeYahoo(prices)}, now=lambda: NOW, history=history)


def _figures(value: str, net_deposits: str) -> Figures:
    return Figures(Decimal(value), Decimal(net_deposits))


async def test_a_successful_refresh_is_snapshotted_for_total_and_each_account(engine: Engine) -> None:
    async with user_simulation(_shell(engine, {"PZU.WA": "60"})) as user:
        await user.open("/")
        user.find(marker="refresh-prices").click()
        await user.should_see("Odświeżono wyceny: 1.")
        for _ in range(50):
            if snapshot_before(engine, TOMORROW, None) is not None:
                break
            await asyncio.sleep(0.05)

    assert snapshot_before(engine, TOMORROW, None) == ValuationSnapshot(NOW, _figures("4100", "4000"))
    assert snapshot_before(engine, TOMORROW, 1) == ValuationSnapshot(NOW, _figures("1100", "1000"))
    assert snapshot_before(engine, TOMORROW, 2) == ValuationSnapshot(NOW, _figures("3000", "3000"))


async def test_a_failed_refresh_saves_no_snapshot(engine: Engine) -> None:
    async with user_simulation(_shell(engine, {})) as user:
        await user.open("/")
        user.find(marker="refresh-prices").click()
        await user.should_see("Bez notowania: PZU.")
        await user.should_see(marker="total-net-deposits", content=_pln("4 000,00"))

    assert snapshot_before(engine, TOMORROW, None) is None


async def test_the_dashboard_shows_the_change_since_the_snapshot_of_an_earlier_day(engine: Engine) -> None:
    # Today the PZU is worth its cost (no Quote): 4000 in all, 1000 on IKE
    save_snapshot(engine, datetime(2026, 10, 9, 18, 2), {None: _figures("3500", "3600"), 1: _figures("950", "1000")})
    save_snapshot(engine, datetime(2026, 10, 16, 9, 0), {None: _figures("9999", "9999")})

    async with user_simulation(_shell(engine, {})) as user:
        await user.open("/")

        await user.should_see(
            marker="since-snapshot",
            content=f"Od 09.10, 18:02: {_pln('+500,00')} ({'+2,86'}{NBSP}%), w tym rynek {_pln('+100,00')}, "
            f"wpłaty netto {_pln('+400,00')}",
        )

        user.find(marker="view-scope").click()
        await user.should_see(marker="scope-menu")
        user.find(marker="scope-1").click()
        await user.should_see(marker="since-snapshot", content=f"Od 09.10, 18:02: {_pln('+50,00')}")

        user.find(marker="view-scope").click()
        await user.should_see(marker="scope-menu")
        user.find(marker="scope-2").click()
        await user.should_see(marker="total-value", content=_pln("3 000,00"))
        await user.should_not_see(marker="since-snapshot")


async def test_there_is_no_change_line_while_history_is_computed(engine: Engine) -> None:
    save_snapshot(engine, datetime(2026, 10, 9, 18, 2), {None: _figures("3500", "3600")})
    computed = asyncio.Event()

    async def slow(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
        await computed.wait()
        return function(*args)

    async with user_simulation(_shell(engine, {}, slow)) as user:
        await user.open("/")
        await user.should_see(marker="total-net-deposits", content="—")
        await user.should_not_see(marker="since-snapshot")

        computed.set()
        await user.should_see(marker="since-snapshot")
