"""The bond data sources in the window (spec 3.4.1): fetched with the price refresh, at start-up even when the prices
are fresh, and a failing source shown in the header."""

import asyncio
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import user_simulation
from sqlalchemy import Engine

from financial_app.domain.bonds import BondDataError, CpiReading, ReferenceRate, SeriesTerms
from financial_app.domain.prices import YAHOO, Quote
from financial_app.persistence.bond_data import bond_data_statuses, load_cpi
from financial_app.persistence.db import init_db
from financial_app.sources.bond_data import MF, BondDataSources
from financial_app.sources.prices import refresh_prices
from financial_app.ui.shell import build_shell

NOW = datetime(2026, 10, 12, 19, 0)
EDO0536 = SeriesTerms(
    "EDO0536", "PL0000119145", date(2026, 5, 1), date(2026, 5, 31), Decimal(100), Decimal("99.9"), Decimal("0.02"),
    (Decimal("0.0535"),), (None,),
)  # fmt: skip
CPI = CpiReading(2026, 8, Decimal("103.4"), Decimal("100.3"))
RATE = ReferenceRate(date(2026, 3, 5), Decimal("0.0375"))


class FakeYahoo:
    name = YAHOO

    def new_refresh(self) -> None:
        pass

    def quote(self, symbol: str, currency: str) -> Quote:
        raise AssertionError("nothing is held")


def _working() -> BondDataSources:
    return BondDataSources(lambda: [EDO0536], lambda: [CPI], lambda: [RATE])


def _mf_down() -> list[SeriesTerms]:
    raise BondDataError("Nie udało się pobrać strony MF z obligacjami. Sprawdź połączenie z internetem.")


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


async def test_the_refresh_button_fetches_the_bond_data(engine: Engine) -> None:
    shell = lambda: build_shell(engine, sources={YAHOO: FakeYahoo()}, now=lambda: NOW, bond_data=_working())  # noqa: E731

    async with user_simulation(shell) as user:
        await user.open("/")
        user.find(marker="refresh-prices").click()
        await user.should_see("Wyceny: 12.10.2026 19:00")

    assert load_cpi(engine) == [CPI]


async def test_a_start_with_fresh_prices_still_fetches_the_bond_data_due_today(engine: Engine) -> None:
    refresh_prices(engine, {}, lambda: NOW)
    shell = lambda: build_shell(  # noqa: E731
        engine, sources={YAHOO: FakeYahoo()}, refresh_at_start=True, now=lambda: NOW, bond_data=_working()
    )

    async with user_simulation(shell) as user:
        await user.open("/")
        await user.should_see("Wyceny: 12.10.2026 19:00")
        for _ in range(50):
            if load_cpi(engine):
                break
            await asyncio.sleep(0.05)

    assert load_cpi(engine) == [CPI]


async def test_a_failing_source_shows_in_the_header_with_its_reason(engine: Engine) -> None:
    sources = BondDataSources(_mf_down, lambda: [CPI], lambda: [RATE])
    shell = lambda: build_shell(engine, sources={YAHOO: FakeYahoo()}, now=lambda: NOW, bond_data=sources)  # noqa: E731

    async with user_simulation(shell) as user:
        await user.open("/")
        await user.should_not_see(marker="bond-data-status")
        user.find(marker="refresh-prices").click()
        await user.should_see("Dane obligacji: 1 błąd")

        user.find(marker="bond-data-status").click()
        with user.scope(marker="bond-data-errors"):
            await user.should_see("Plik MF (obligacje)")
            await user.should_see("Sprawdź połączenie z internetem")
            await user.should_see("Brak pobranych danych.")

    assert bond_data_statuses(engine)[MF].error is not None
