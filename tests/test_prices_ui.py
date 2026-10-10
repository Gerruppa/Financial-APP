"""Source Symbols in the Instrument dialog, Portfolio valuation from Quotes (issue #30) and the refresh status with
the price badges (issue #37), without a browser."""

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
from financial_app.persistence.instruments import add_instrument, list_instruments
from financial_app.persistence.quotes import save_quote
from financial_app.persistence.transactions import add_transaction
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
FRIDAY = date(2026, 10, 9)
AKCJE_POLSKIE = 2
OBLIGACJE_SKARBOWE_POLSKIE = 4
INNE = 11


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


def _held_pzu(engine: Engine, manual_price: Decimal | None = None) -> int:
    """10 PZU bought for 400 zł, with the Yahoo symbol PZU.WA; returns its id."""
    return _held(engine, InstrumentDraft("PZU", AKCJE_POLSKIE, "PLN", "GPW", manual_price, {YAHOO: "PZU.WA"}))


def _held(engine: Engine, draft: InstrumentDraft) -> int:
    """10 units of a new Instrument bought for 400 zł on a new Account; returns the Instrument's id."""
    account = add_account(engine, AccountDraft(f"Konto {draft.name}", "XTB", AccountType.REGULAR, ("PLN",)))
    instrument = add_instrument(engine, draft)
    add_transaction(engine, TransactionDraft(account.id, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(1000)))
    add_transaction(
        engine, buy_or_sell(account.id, date(2026, 1, 5), TransactionType.BUY, instrument.id, Decimal(10), Decimal(40))
    )
    return instrument.id


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


async def test_before_the_first_refresh_the_header_says_there_is_none(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine, sources={YAHOO: FakeYahoo({})})) as user:
        await user.open("/")

        await user.should_see("Wyceny: brak")


async def test_one_failing_instrument_shows_one_error_with_its_reason_and_the_others_refresh(engine: Engine) -> None:
    _held_pzu(engine)
    _held(engine, InstrumentDraft("AAA", AKCJE_POLSKIE, "PLN", source_symbols={YAHOO: "AAA.WA"}))

    async with user_simulation(lambda: build_shell(engine, sources={YAHOO: FakeYahoo({"PZU.WA": "45.12"})})) as user:
        await user.open("/portfolio")
        user.find(marker="refresh-prices").click()

        with user.scope(marker="portfolio"):
            await user.should_see(f"451,20{NBSP}zł")
        await user.should_see("1 błąd")
        user.find(marker="price-status").click()
        with user.scope(marker="price-errors"):
            await user.should_see("AAA")
            await user.should_see("Yahoo: Yahoo nie zna symbolu „AAA.WA”.")
            await user.should_not_see("PZU")


async def test_a_failed_refresh_keeps_the_earlier_quote_marked_stale_until_a_refresh_succeeds(engine: Engine) -> None:
    pzu = _held_pzu(engine)
    save_quote(engine, pzu, Quote(Decimal("44"), "PLN", date(2026, 10, 8), YAHOO), datetime(2026, 10, 8, 18, 0))
    yahoo = FakeYahoo({})

    async with user_simulation(lambda: build_shell(engine, sources={YAHOO: yahoo})) as user:
        await user.open("/portfolio")
        user.find(marker="refresh-prices").click()

        with user.scope(marker="portfolio"):
            await user.should_see("nieaktualna")
            await user.should_see(f"440,00{NBSP}zł")  # still valued at the earlier Quote
            await user.should_see("08.10.2026")

        yahoo.prices["PZU.WA"] = "45.12"
        user.find(marker="refresh-prices").click()

        with user.scope(marker="portfolio"):
            await user.should_see(f"451,20{NBSP}zł")
            await user.should_not_see("nieaktualna")
        await user.should_see("Wyceny: ")
        await user.should_not_see("błąd")


async def test_a_bond_series_waits_for_stage_3_and_is_not_an_error(engine: Engine) -> None:
    _held(engine, InstrumentDraft("EDO0735", OBLIGACJE_SKARBOWE_POLSKIE, "PLN", manual_price=Decimal("104.5")))

    async with user_simulation(lambda: build_shell(engine, sources={YAHOO: FakeYahoo({})})) as user:
        await user.open("/portfolio")
        user.find(marker="refresh-prices").click()

        with user.scope(marker="portfolio"):
            await user.should_see("do etapu 3")
            await user.should_see(f"1{NBSP}045,00{NBSP}zł")
        await user.should_see("Wyceny: ")
        await user.should_not_see("błąd")


async def test_a_manual_price_and_an_instrument_without_a_source_have_their_badges(engine: Engine) -> None:
    _held_pzu(engine, manual_price=Decimal(50))
    _held(engine, InstrumentDraft("Fundusz", INNE, "PLN"))

    async with user_simulation(lambda: build_shell(engine, sources={YAHOO: FakeYahoo({})})) as user:
        await user.open("/portfolio")

        with user.scope(marker="portfolio"):
            await user.should_see("ręczna")
            await user.should_see("bez źródła")
