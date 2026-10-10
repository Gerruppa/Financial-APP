"""Source Symbols in the Instrument dialog, Portfolio valuation from Quotes (issue #30) and the refresh status with
the price badges (issue #37), Bossa (issue #31) and the fund sources (issue #32), without a browser."""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.error import URLError

import pytest
from nicegui.testing import user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.prices import ANALIZY, BANKIER, BOSSA, YAHOO, PriceSourceError, Quote
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_instruments
from financial_app.persistence.quotes import save_quote
from financial_app.persistence.transactions import add_transaction
from financial_app.sources.analizy import AnalizySource
from financial_app.sources.bankier import BankierSource
from financial_app.sources.bossa import BossaSource
from financial_app.sources.prices import PriceSource
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

    def new_refresh(self) -> None:
        pass

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


def _saved_bossa(url: str) -> str:
    category = url.rsplit("/", 1)[1]
    return (Path(__file__).parent / "fixtures" / "bossa" / f"{category}.json").read_text(encoding="utf-8")


async def test_the_bossa_symbol_is_saved_with_the_instrument_and_shown_in_the_list(engine: Engine) -> None:
    add_instrument(engine, InstrumentDraft("PZU", AKCJE_POLSKIE, "PLN", "GPW"))

    async with user_simulation(lambda: build_shell(engine, sources={YAHOO: FakeYahoo({})})) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-instrument").click()
        user.find(marker="instrument-symbol-bossa").clear().type("PZU")
        user.find("Zapisz").click()
        await user.should_not_see(marker="instrument-dialog")

        assert list_instruments(engine)[0].source_symbols == {BOSSA: "PZU"}
        await user.should_see("Bossa PZU")


async def test_a_polish_share_is_valued_from_bossa_before_yahoo(engine: Engine) -> None:
    _held(engine, InstrumentDraft("PZU", AKCJE_POLSKIE, "PLN", "GPW", source_symbols={BOSSA: "PZU", YAHOO: "PZU.WA"}))
    sources: dict[str, PriceSource] = {BOSSA: BossaSource(_saved_bossa), YAHOO: FakeYahoo({"PZU.WA": "45.12"})}

    async with user_simulation(lambda: build_shell(engine, sources=sources)) as user:
        await user.open("/portfolio")
        user.find(marker="refresh-prices").click()

        with user.scope(marker="portfolio"):
            await user.should_see(f"698,20{NBSP}zł")  # 10 × 69,82 from Bossa
            await user.should_see("02.10.2026")


async def test_when_bossa_fails_a_polish_share_is_valued_from_yahoo(engine: Engine) -> None:
    _held(engine, InstrumentDraft("PZU", AKCJE_POLSKIE, "PLN", "GPW", source_symbols={BOSSA: "PZU", YAHOO: "PZU.WA"}))

    def offline(url: str) -> str:
        raise URLError("offline")

    sources: dict[str, PriceSource] = {BOSSA: BossaSource(offline), YAHOO: FakeYahoo({"PZU.WA": "45.12"})}

    async with user_simulation(lambda: build_shell(engine, sources=sources)) as user:
        await user.open("/portfolio")
        user.find(marker="refresh-prices").click()

        with user.scope(marker="portfolio"):
            await user.should_see(f"451,20{NBSP}zł")
        await user.should_not_see("błąd")


FIXTURES = Path(__file__).parent / "fixtures"


def _saved_analizy(url: str) -> str | None:
    path = FIXTURES / "analizy" / f"{url.rsplit('/', 1)[1]}.json"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _saved_bankier(url: str) -> str | None:
    kind, symbol = url.removeprefix("https://www.bankier.pl/").split("/notowania/")
    path = FIXTURES / "bankier" / f"{kind}_{symbol}.html"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _fund_sources(analizy: Callable[[str], str | None] = _saved_analizy) -> dict[str, PriceSource]:
    return {
        ANALIZY: AnalizySource(analizy),
        BANKIER: BankierSource(_saved_bankier),
        YAHOO: FakeYahoo({}),
        BOSSA: BossaSource(_saved_bossa),
    }


async def test_the_analizy_and_bankier_symbols_are_saved_with_the_instrument(engine: Engine) -> None:
    add_instrument(engine, InstrumentDraft("PPK inPZU 2060", INNE, "PLN"))

    async with user_simulation(lambda: build_shell(engine, sources=_fund_sources())) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-instrument").click()
        user.find(marker="instrument-symbol-analizy").clear().type("PZU60")
        user.find(marker="instrument-symbol-bankier").clear().type("PZU60")
        user.find("Zapisz").click()
        await user.should_not_see(marker="instrument-dialog")

        assert list_instruments(engine)[0].source_symbols == {ANALIZY: "PZU60", BANKIER: "PZU60"}
        await user.should_see("analizy.pl PZU60")


async def test_a_fund_is_valued_from_analizy_at_its_newest_valuation_day(engine: Engine) -> None:
    _held(engine, InstrumentDraft("PPK inPZU 2060", INNE, "PLN", source_symbols={ANALIZY: "PZU60", BANKIER: "PZU60"}))

    async with user_simulation(lambda: build_shell(engine, sources=_fund_sources())) as user:
        await user.open("/portfolio")
        user.find(marker="refresh-prices").click()

        with user.scope(marker="portfolio"):
            await user.should_see(f"1{NBSP}184,90{NBSP}zł")  # 10 × 118,49
            await user.should_see("08.10.2026")


async def test_when_analizy_fails_a_fund_is_valued_from_bankier(engine: Engine) -> None:
    _held(engine, InstrumentDraft("QUERCUS Silver", INNE, "PLN", source_symbols={ANALIZY: "QRS32", BANKIER: "QRS32"}))

    def offline(url: str) -> str | None:
        raise URLError("offline")

    async with user_simulation(lambda: build_shell(engine, sources=_fund_sources(offline))) as user:
        await user.open("/portfolio")
        user.find(marker="refresh-prices").click()

        with user.scope(marker="portfolio"):
            await user.should_see(f"2{NBSP}038,30{NBSP}zł")  # 10 × 203,83 from bankier.pl
        await user.should_not_see("błąd")
