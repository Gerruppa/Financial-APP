"""The price source help window of an Instrument without a price (issue #274), on a fake Yahoo, without a browser."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import InstrumentDraft, InstrumentType
from financial_app.domain.prices import YAHOO, PriceSourceError, Quote
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument
from financial_app.persistence.transactions import add_transaction
from financial_app.ui.shell import build_shell

AKCJE_ZAGRANICZNE = 3
INNE = 11


class FakeYahoo:
    name = YAHOO

    def __init__(self, prices: dict[str, str]) -> None:
        self.prices = prices

    def new_refresh(self) -> None:
        pass

    def quote(self, symbol: str, currency: str) -> Quote:
        if symbol not in self.prices:
            raise PriceSourceError(f"Yahoo nie zna symbolu „{symbol}”.")
        return Quote(Decimal(self.prices[symbol]), currency, date(2026, 10, 9), YAHOO)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _held(engine: Engine, draft: InstrumentDraft) -> None:
    """10 units of a new Instrument bought on a new Account."""
    account = add_account(engine, AccountDraft("Konto", "XTB", AccountType.REGULAR, ("PLN",)))
    instrument = add_instrument(engine, draft)
    add_transaction(engine, TransactionDraft(account.id, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(1000)))
    currency = instrument.quote_currency
    rate = None if currency == "PLN" else NbpRate(currency, Decimal(4), date(2026, 1, 2), "001/A/NBP/2026")
    buy = buy_or_sell(
        account.id, date(2026, 1, 5), TransactionType.BUY, instrument.id, Decimal(10), Decimal(40), nbp_rate=rate
    )
    add_transaction(engine, buy)


async def _open_guide(user: User) -> None:
    await user.open("/ustawienia")
    user.find(marker="unpriced-guide").click()
    await user.should_see(marker="price-guide-wizard")


async def test_a_checked_symbol_is_saved_as_the_instruments_source(engine: Engine) -> None:
    _held(
        engine,
        InstrumentDraft(
            "Vanguard FTSE All-World", AKCJE_ZAGRANICZNE, "EUR", "Xetra", instrument_type=InstrumentType.ETF
        ),
    )

    async with user_simulation(lambda: build_shell(engine, sources={YAHOO: FakeYahoo({"VWCE.DE": "120.5"})})) as user:
        await _open_guide(user)
        with user.scope(marker="price-guide-wizard"):
            await user.should_see("VWCE.DE (Xetra, EUR)")
        user.find(marker="price-guide-source-yahoo").click()
        await user.should_see(marker="price-guide-step-2")

        user.find(marker="price-guide-symbol").type("VWCE")
        user.find(marker="price-guide-check").click()
        with user.scope(marker="price-guide-result"):
            await user.should_see("Yahoo nie zna symbolu „VWCE”.")
        user.find(marker="price-guide-symbol").clear().type("VWCE.DE")
        user.find(marker="price-guide-check").click()
        with user.scope(marker="price-guide-result"):
            await user.should_see("120,50")
        user.find(marker="price-guide-next").click()

        await user.should_see(marker="price-guide-step-3")
        with user.scope(marker="price-guide-wizard"):
            await user.should_see("Yahoo: symbol VWCE.DE")
        user.find(marker="price-guide-save").click()
        await user.should_see(marker="price-guide-saved")
        with user.scope(marker="unpriced"):
            await user.should_see("czeka na odświeżenie wycen")


async def test_the_next_step_waits_for_a_successful_check_of_the_typed_symbol(engine: Engine) -> None:
    _held(engine, InstrumentDraft("Apple", AKCJE_ZAGRANICZNE, "USD", "Nasdaq", instrument_type=InstrumentType.STOCK))

    async with user_simulation(lambda: build_shell(engine, sources={YAHOO: FakeYahoo({"AAPL": "230"})})) as user:
        await _open_guide(user)
        user.find(marker="price-guide-source-yahoo").click()
        next_button = user.find(marker="price-guide-next", kind=ui.button).elements.pop()
        assert not next_button.enabled

        user.find(marker="price-guide-symbol").type("AAPL")
        user.find(marker="price-guide-check").click()
        with user.scope(marker="price-guide-result"):
            await user.should_see("230,00")
        assert next_button.enabled

        user.find(marker="price-guide-symbol").type("X")
        assert not next_button.enabled


async def test_a_manual_price_is_saved_when_no_source_quotes_the_instrument(engine: Engine) -> None:
    _held(engine, InstrumentDraft("Udziały w spółce", INNE, "PLN", instrument_type=InstrumentType.OTHER))

    async with user_simulation(lambda: build_shell(engine, sources={YAHOO: FakeYahoo({})})) as user:
        await _open_guide(user)
        user.find(marker="price-guide-source-manual").click()
        user.find(marker="price-guide-price").type("abc")
        with user.scope(marker="price-guide-wizard"):
            await user.should_see("Cena ręczna musi być liczbą, a nie „abc”.")
        user.find(marker="price-guide-price").clear().type("150,5")
        user.find(marker="price-guide-next").click()
        user.find(marker="price-guide-save").click()
        await user.should_see(marker="price-guide-saved")
        with user.scope(marker="instruments"):
            await user.should_see("cena ręczna 150,50 PLN")
