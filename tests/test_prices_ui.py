"""Source Symbols in the Instrument dialog and Portfolio valuation from Quotes (issue #30), without a browser."""

from datetime import date
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
from financial_app.persistence.instruments import add_instrument, list_instruments
from financial_app.persistence.transactions import add_transaction
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
FRIDAY = date(2026, 10, 9)
AKCJE_POLSKIE = 2


class FakeYahoo:
    name = YAHOO

    def __init__(self, prices: dict[str, str]) -> None:
        self.prices = prices

    def quote(self, symbol: str, currency: str) -> Quote:
        if symbol not in self.prices:
            raise PriceSourceError(f"Yahoo nie zna symbolu „{symbol}”.")
        return Quote(Decimal(self.prices[symbol]), currency, FRIDAY, YAHOO)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _held_pzu(engine: Engine, manual_price: Decimal | None = None) -> None:
    """10 PZU bought for 400 zł, with the Yahoo symbol PZU.WA."""
    account = add_account(engine, AccountDraft("Konto", "XTB", AccountType.REGULAR, ("PLN",)))
    pzu = add_instrument(
        engine, InstrumentDraft("PZU", AKCJE_POLSKIE, "PLN", "GPW", manual_price, source_symbols={YAHOO: "PZU.WA"})
    )
    add_transaction(engine, TransactionDraft(account.id, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(1000)))
    add_transaction(
        engine, buy_or_sell(account.id, date(2026, 1, 5), TransactionType.BUY, pzu.id, Decimal(10), Decimal(40))
    )


async def test_the_yahoo_symbol_is_saved_with_the_instrument_and_shown_when_editing(engine: Engine) -> None:
    add_instrument(engine, InstrumentDraft("ISAC", 3, "USD", "LSE"))

    async with user_simulation(lambda: build_shell(engine, sources={YAHOO: FakeYahoo({})})) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-instrument").click()
        user.find(marker="instrument-symbol-yahoo").clear().type("ISAC.L")
        user.find("Zapisz").click()
        await user.should_not_see(marker="instrument-dialog")

        assert list_instruments(engine)[0].source_symbols == {YAHOO: "ISAC.L"}
        user.find(marker="edit-instrument").click()
        await user.should_see("ISAC.L")


async def test_after_a_refresh_the_portfolio_values_a_position_at_its_quote_with_its_date(engine: Engine) -> None:
    _held_pzu(engine)

    async with user_simulation(lambda: build_shell(engine, sources={YAHOO: FakeYahoo({"PZU.WA": "45.12"})})) as user:
        await user.open("/portfolio")
        with user.scope(marker="portfolio"):
            await user.should_see("brak ceny")
        user.find(marker="refresh-prices").click()

        with user.scope(marker="portfolio"):
            await user.should_see(f"45,12{NBSP}zł")
            await user.should_see("09.10.2026")
            await user.should_see(f"451,20{NBSP}zł")  # value of 10 units
            await user.should_see(f"+51,20{NBSP}zł")


async def test_a_manual_price_still_wins_and_the_quote_is_shown_beside_it(engine: Engine) -> None:
    _held_pzu(engine, manual_price=Decimal(50))

    async with user_simulation(lambda: build_shell(engine, sources={YAHOO: FakeYahoo({"PZU.WA": "45.12"})})) as user:
        await user.open("/portfolio")
        user.find(marker="refresh-prices").click()

        with user.scope(marker="portfolio"):
            await user.should_see(f"Yahoo: 45,12{NBSP}zł (09.10.2026)")
            await user.should_see(f"500,00{NBSP}zł")  # valued at the Manual Price
