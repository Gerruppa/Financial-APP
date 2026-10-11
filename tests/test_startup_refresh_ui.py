"""Refreshing the prices in the background at start-up (issue #38, spec 4.1), with fake sources and a fixed clock."""

import threading
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.prices import YAHOO, PriceSourceError, Quote
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument
from financial_app.persistence.transactions import add_transaction
from financial_app.sources.prices import refresh_prices
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
FRIDAY = date(2026, 10, 9)
FRIDAY_EVENING = datetime(2026, 10, 9, 19, 0)
AKCJE_POLSKIE = 2


class FakeYahoo:
    """Yahoo answering from ``prices``; with ``gate`` set, each Quote waits until the test opens it."""

    name = YAHOO

    def __init__(self, prices: dict[str, str], gate: threading.Event | None = None) -> None:
        self.prices = prices
        self.gate = gate
        self.asked: list[str] = []

    def new_refresh(self) -> None:
        pass

    def quote(self, symbol: str, currency: str) -> Quote:
        self.asked.append(symbol)
        if self.gate is not None:
            self.gate.wait(timeout=10)
        if symbol not in self.prices:
            raise PriceSourceError("Brak połączenia z Yahoo.")
        return Quote(Decimal(self.prices[symbol]), currency, FRIDAY, YAHOO)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = init_db(tmp_path / "app.sqlite3")
    account = add_account(engine, AccountDraft("Konto", "XTB", AccountType.REGULAR, ("PLN",)))
    pzu = add_instrument(engine, InstrumentDraft("PZU", AKCJE_POLSKIE, "PLN", source_symbols={YAHOO: "PZU.WA"}))
    add_transaction(engine, TransactionDraft(account.id, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(1000)))
    add_transaction(
        engine, buy_or_sell(account.id, date(2026, 1, 5), TransactionType.BUY, pzu.id, Decimal(10), Decimal(40))
    )
    return engine


def _shell(engine: Engine, yahoo: FakeYahoo, now: datetime) -> Callable[[], None]:
    return lambda: build_shell(engine, sources={YAHOO: yahoo}, refresh_at_start=True, now=lambda: now)


async def test_a_start_after_the_close_refreshes_and_the_portfolio_shows_the_quote(engine: Engine) -> None:
    refresh_prices(engine, {YAHOO: FakeYahoo({"PZU.WA": "44"})}, lambda: datetime(2026, 10, 9, 12, 0))

    async with user_simulation(_shell(engine, FakeYahoo({"PZU.WA": "45.12"}), FRIDAY_EVENING)) as user:
        await user.open("/portfolio")

        with user.scope(marker="portfolio"):
            await user.should_see(f"451,20{NBSP}zł")
        await user.should_see("Wyceny: 09.10.2026 19:00")


async def test_a_second_start_the_same_evening_does_not_refresh(engine: Engine) -> None:
    refresh_prices(engine, {YAHOO: FakeYahoo({"PZU.WA": "44"})}, lambda: datetime(2026, 10, 9, 18, 0))
    yahoo = FakeYahoo({"PZU.WA": "45.12"})

    async with user_simulation(_shell(engine, yahoo, FRIDAY_EVENING)) as user:
        await user.open("/portfolio")

        with user.scope(marker="portfolio"):
            await user.should_see(f"440,00{NBSP}zł")
        await user.should_see("Wyceny: 09.10.2026 18:00")
    assert yahoo.asked == []


async def test_a_weekend_start_after_a_friday_evening_refresh_does_not_refresh(engine: Engine) -> None:
    refresh_prices(engine, {YAHOO: FakeYahoo({"PZU.WA": "44"})}, lambda: datetime(2026, 10, 9, 18, 0))
    yahoo = FakeYahoo({"PZU.WA": "45.12"})

    async with user_simulation(_shell(engine, yahoo, datetime(2026, 10, 11, 10, 0))) as user:
        await user.open("/")
        await user.should_see("Wyceny: 09.10.2026 18:00")
    assert yahoo.asked == []


async def test_the_window_is_usable_while_the_start_up_refresh_runs(engine: Engine) -> None:
    gate = threading.Event()
    try:
        async with user_simulation(_shell(engine, FakeYahoo({"PZU.WA": "45.12"}, gate), FRIDAY_EVENING)) as user:
            await user.open("/")
            await user.should_see("Wyceny: odświeżanie…")

            user.find("Transakcje").click()
            await user.should_see(marker="transactions")

            gate.set()
            await user.should_see("Wyceny: 09.10.2026 19:00")
    finally:
        gate.set()


async def test_with_no_network_the_app_starts_and_shows_the_errors(engine: Engine) -> None:
    async with user_simulation(_shell(engine, FakeYahoo({}), FRIDAY_EVENING)) as user:
        await user.open("/portfolio")

        await user.should_see("1 błąd")
        with user.scope(marker="portfolio"):
            await user.should_see("brak ceny")


async def test_reloading_the_window_during_the_start_up_refresh_joins_it_instead_of_starting_another(
    engine: Engine,
) -> None:
    gate = threading.Event()
    yahoo = FakeYahoo({"PZU.WA": "45.12"}, gate)
    try:
        async with user_simulation(_shell(engine, yahoo, FRIDAY_EVENING)) as user:
            await user.open("/")
            await user.should_see("Wyceny: odświeżanie…")

            await user.open("/")
            await user.should_see("Wyceny: odświeżanie…")
            gate.set()
            await user.should_see("Wyceny: 09.10.2026 19:00")
    finally:
        gate.set()
    assert yahoo.asked == ["PZU.WA"]


async def test_an_unexpected_error_in_the_refresh_is_shown(engine: Engine) -> None:
    class BrokenYahoo(FakeYahoo):
        def new_refresh(self) -> None:
            raise RuntimeError("baza zablokowana")

    async with user_simulation(_shell(engine, BrokenYahoo({}), FRIDAY_EVENING)) as user:
        await user.open("/")

        await user.should_see("Odświeżanie wycen nie powiodło się: baza zablokowana")
        await user.should_see("Wyceny: brak")
