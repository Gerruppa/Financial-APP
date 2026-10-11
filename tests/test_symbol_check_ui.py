"""The "Sprawdź" button beside each Source Symbol in the Instrument dialog (issue #39, spec 4.1), on fake sources
without a browser or the network."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import user_simulation
from sqlalchemy import Engine

from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.prices import BOSSA, YAHOO, CurrencyMismatchError, PriceSourceError, Quote
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_instruments
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
FRIDAY = date(2026, 10, 9)
AKCJE_ZAGRANICZNE = 3


class FakeSource:
    """Quotes each known symbol in its own currency, like the real sources: another currency than the Instrument's is
    a ``CurrencyMismatchError`` carrying the Quote."""

    def __init__(self, name: str, prices: dict[str, tuple[str, str]]) -> None:
        self.name = name
        self.prices = prices

    def new_refresh(self) -> None:
        pass

    def quote(self, symbol: str, currency: str) -> Quote:
        if symbol not in self.prices:
            raise PriceSourceError(f"{self.name} nie zna symbolu „{symbol}”.")
        price, source_currency = self.prices[symbol]
        quote = Quote(Decimal(price), source_currency, FRIDAY, self.name)
        if source_currency != currency:
            raise CurrencyMismatchError(f"{self.name}: {source_currency} zamiast {currency}.", quote)
        return quote


class OfflineSource(FakeSource):
    def quote(self, symbol: str, currency: str) -> Quote:
        raise PriceSourceError("Nie udało się połączyć z Yahoo. Sprawdź połączenie z internetem.")


SOURCES = {
    YAHOO: FakeSource(YAHOO, {"AAPL": ("254.63", "USD"), "ISAC.L": ("123.91", "USD")}),
    BOSSA: FakeSource(BOSSA, {"PZU": ("69.82", "PLN")}),
}


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


async def test_a_known_symbol_shows_its_price_currency_and_date(engine: Engine) -> None:
    add_instrument(engine, InstrumentDraft("Apple", AKCJE_ZAGRANICZNE, "USD", source_symbols={YAHOO: "AAPL"}))

    async with user_simulation(lambda: build_shell(engine, sources=SOURCES)) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-instrument").click()
        user.find(marker="check-symbol-yahoo").click()

        with user.scope(marker="symbol-check-yahoo"):
            await user.should_see(f"254,63{NBSP}USD · 09.10.2026")


async def test_another_currency_than_the_instruments_shows_a_warning_beside_the_sources_price(engine: Engine) -> None:
    add_instrument(engine, InstrumentDraft("ISAC", AKCJE_ZAGRANICZNE, "GBP", source_symbols={YAHOO: "ISAC.L"}))

    async with user_simulation(lambda: build_shell(engine, sources=SOURCES)) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-instrument").click()
        user.find(marker="check-symbol-yahoo").click()

        with user.scope(marker="symbol-check-yahoo"):
            await user.should_see(f"123,91{NBSP}USD · 09.10.2026")
            await user.should_see("yahoo: USD zamiast GBP.")


async def test_the_check_uses_the_symbol_and_currency_typed_in_the_form(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine, sources=SOURCES)) as user:
        await user.open("/ustawienia")
        user.find("Dodaj instrument").click()
        user.find(marker="instrument-symbol-bossa").type("PZU")
        user.find(marker="check-symbol-bossa").click()

        with user.scope(marker="symbol-check-bossa"):
            await user.should_see(f"69,82{NBSP}zł · 09.10.2026")


async def test_an_unknown_symbol_shows_the_error_and_the_instrument_still_saves(engine: Engine) -> None:
    add_instrument(engine, InstrumentDraft("Apple", AKCJE_ZAGRANICZNE, "USD"))

    async with user_simulation(lambda: build_shell(engine, sources=SOURCES)) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-instrument").click()
        user.find(marker="instrument-symbol-yahoo").type("NOSUCH")
        user.find(marker="check-symbol-yahoo").click()
        with user.scope(marker="symbol-check-yahoo"):
            await user.should_see("yahoo nie zna symbolu „NOSUCH”.")

        user.find("Zapisz").click()
        await user.should_not_see(marker="instrument-dialog")

    assert list_instruments(engine)[0].source_symbols == {YAHOO: "NOSUCH"}


async def test_without_a_connection_the_check_says_so(engine: Engine) -> None:
    offline = OfflineSource(YAHOO, {})
    add_instrument(engine, InstrumentDraft("Apple", AKCJE_ZAGRANICZNE, "USD", source_symbols={YAHOO: "AAPL"}))

    async with user_simulation(lambda: build_shell(engine, sources={YAHOO: offline})) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-instrument").click()
        user.find(marker="check-symbol-yahoo").click()

        with user.scope(marker="symbol-check-yahoo"):
            await user.should_see("Nie udało się połączyć z Yahoo.")


async def test_a_source_the_app_has_no_module_for_has_no_check_button(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine, sources={YAHOO: SOURCES[YAHOO]})) as user:
        await user.open("/ustawienia")
        user.find("Dodaj instrument").click()

        await user.should_see(marker="check-symbol-yahoo")
        await user.should_not_see(marker="check-symbol-bossa")
        await user.should_not_see(marker="check-symbol-stooq")
