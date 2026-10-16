"""The Podsumowanie sprzedaży tab (issue #92, spec 10): the View Scope's Sale Pairs sold in the period and their
statistics."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell, dividend
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import add_transactions
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
NOW = datetime(2026, 10, 12, 9, 0)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """IKE: PZU bought 10 at 50 on 5.01 and sold at 60 on 4.03 with a 20 PLN Dividend in between; XTB: CDR bought 10
    at 100 on 5.01 and sold at 80 on 4.07."""
    engine = init_db(tmp_path / "app.sqlite3")
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    xtb = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id
    shares = next(c for c in list_asset_classes(engine) if c.name == "Akcje polskie")
    pzu = add_instrument(engine, InstrumentDraft("PZU", shares.id, "PLN")).id
    cdr = add_instrument(engine, InstrumentDraft("CDR", shares.id, "PLN")).id
    buy, sell = TransactionType.BUY, TransactionType.SELL
    add_transactions(
        engine,
        [
            TransactionDraft(ike, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(1000)),
            TransactionDraft(xtb, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(1000)),
            buy_or_sell(ike, date(2026, 1, 5), buy, pzu, Decimal(10), Decimal(50)),
            buy_or_sell(xtb, date(2026, 1, 5), buy, cdr, Decimal(10), Decimal(100)),
            dividend(ike, date(2026, 2, 2), Decimal(20), instrument_id=pzu),
            buy_or_sell(ike, date(2026, 3, 4), sell, pzu, Decimal(10), Decimal(60)),
            buy_or_sell(xtb, date(2026, 7, 4), sell, cdr, Decimal(10), Decimal(80)),
        ],
    )
    return engine


def _rows(user: User) -> list[list[str]]:
    rows = sorted(user.find(marker="sale-row").elements, key=lambda element: element.id)
    return [[d.text for d in row.descendants() if isinstance(d, ui.label)] for row in rows]


def _pln(text: str) -> str:
    return f"{text}{NBSP}zł"


async def test_the_pairs_and_their_statistics_since_inception(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine, now=lambda: NOW)) as user:
        await user.open("/sprzedaz")
        await user.should_see(marker="sale-row")
        with user.scope(marker="period-selector"):
            user.find("Od początku").click()

        await user.should_see(marker="sale-count", content="2 pary")
        await user.should_see(marker="sale-win-rate", content=f"50,00{NBSP}%")
        await user.should_see(marker="sale-result", content=_pln("-100,00"))
        await user.should_see(marker="sale-result-dividends", content=_pln("-80,00"))
        await user.should_see(marker="sale-best", content=_pln("+100,00"))
        await user.should_see(marker="sale-worst", content=_pln("-200,00"))
        cdr, pzu = _rows(user)
        assert cdr[:4] == ["CDR", "XTB", "05.01.2026", "04.07.2026"]
        assert pzu == [
            "PZU",
            "IKE",
            "05.01.2026",
            "04.03.2026",
            "10",
            _pln("500,00"),
            _pln("600,00"),
            _pln("+100,00"),
            f"+20,00{NBSP}%",
            "58",
            _pln("20,00"),
            _pln("+120,00"),
            f"+24,00{NBSP}%",
        ]


async def test_an_account_scope_keeps_its_own_sales(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine, now=lambda: NOW)) as user:
        await user.open("/sprzedaz")
        with user.scope(marker="period-selector"):
            user.find("Od początku").click()
        await user.should_see(marker="sale-row")
        user.find(marker="view-scope").click()
        await user.should_see(marker="scope-menu")
        user.find(marker="scope-1").click()

        await user.should_see(marker="sale-count", content="1 para")
        assert [row[0] for row in _rows(user)] == ["PZU"]


async def test_names_wrap_while_dates_and_numbers_stay_on_one_line(engine: Engine) -> None:
    """Issue #116: a long Instrument or Account name wraps in its own column instead of running over the next one."""
    async with user_simulation(lambda: build_shell(engine, now=lambda: NOW)) as user:
        await user.open("/sprzedaz")
        with user.scope(marker="period-selector"):
            user.find("Od początku").click()
        await user.should_see(marker="sale-row")

        row = sorted(user.find(marker="sale-row").elements, key=lambda element: element.id)[0]
        assert "whitespace-nowrap" not in row.classes
        cells = [d for d in row.descendants() if isinstance(d, ui.label)]
        for name in cells[:2]:
            assert {"break-words", "min-w-0"} <= set(name.classes)
        for value in cells[2:]:
            assert "whitespace-nowrap" in value.classes
        headers = {h.text: h for h in user.find(marker="sale-header").elements if isinstance(h, ui.label)}
        assert "text-right" not in headers["Instrument"].classes
        assert "text-right" not in headers["Sprzedaż"].classes
        assert "text-right" in headers["Liczba"].classes
        assert "text-right" in headers["Rentowność z dyw."].classes


async def test_a_period_without_sales_says_so(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine, now=lambda: NOW)) as user:
        await user.open("/sprzedaz")
        with user.scope(marker="period-selector"):
            user.find("1M").click()

        await user.should_see(marker="sale-empty")
