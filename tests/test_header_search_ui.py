"""The header search and the Instrument Card (issue #175), on a test search and history without the network."""

import gc
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instrument_search import FoundListing, FoundListings, InstrumentSearch
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.prices import BOSSA, YAHOO, Quote
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.history import save_quote_history
from financial_app.persistence.instruments import add_instrument, list_asset_classes, list_instruments
from financial_app.persistence.transactions import add_transactions
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates
from financial_app.sources.portfolio_history import PortfolioHistory
from financial_app.ui.instrument_card import ListingHistory
from financial_app.ui.shell import build_shell

TODAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 9, 0)

VUAA = FoundListing(
    name="Vanguard S&P 500 UCITS ETF USD Acc",
    symbol="VUAA.L",
    market="LSE",
    currency="USD",
    source_symbols={YAHOO: "VUAA.L"},
    isin="IE00BFMXXD54",
    fund=True,
    source="Yahoo",
)


class FixedSearch:
    """Gives ``results`` with ``notes`` for any query."""

    def __init__(self, results: list[FoundListing], notes: tuple[str, ...] = ()) -> None:
        self.results, self.notes = results, notes

    def search(self, query: str) -> FoundListings:
        return FoundListings(self.results, self.notes)


class FixedHistory:
    """Gives every listing the same three closes."""

    def closes(self, listing: FoundListing, last: date) -> list[Quote]:
        return [
            Quote(Decimal(price), listing.currency, date.fromisoformat(day), YAHOO)
            for day, price in [("2025-12-31", "125"), ("2026-10-19", "140"), ("2026-10-20", "147")]
        ]


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


async def _inline(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
    return function(*args)


def _shell(engine: Engine, search: InstrumentSearch, history: ListingHistory) -> Callable[[], None]:
    """The window on ``search`` and the card's ``history``, its History computed inline rather than in the process
    pool, with no Quotes fetched."""
    quotes = QuoteHistory(engine, lambda url: "Brak danych", lambda: TODAY, lambda: NOW, lambda url: None)
    portfolio = PortfolioHistory(engine, quotes, NbpRates(engine), lambda: TODAY, _inline)
    return lambda: build_shell(engine, now=lambda: NOW, search=search, card_history=history, history=portfolio)


def _class_id(engine: Engine, name: str) -> int:
    return next(c.id for c in list_asset_classes(engine) if c.name == name)


async def test_an_own_instrument_is_listed_while_typing_and_opens_its_card(engine: Engine) -> None:
    add_instrument(
        engine,
        InstrumentDraft("CD Projekt", _class_id(engine, "Akcje polskie"), "PLN", source_symbols={YAHOO: "CDR.WA"}),
    )
    search, history = FixedSearch([]), FixedHistory()
    async with user_simulation(_shell(engine, search, history)) as user:
        await user.open("/")
        user.find(marker="header-search").type("projekt")
        await user.should_see("Twoje instrumenty")

        user.find(marker="own-result").click()

        await user.should_see(marker="instrument-card")
        await user.should_see("147,00 zł")
        await user.should_see(marker="card-edit")


async def test_a_card_opened_before_the_search_answers_stays_open_when_the_results_redraw(engine: Engine) -> None:
    add_instrument(
        engine,
        InstrumentDraft("CD Projekt", _class_id(engine, "Akcje polskie"), "PLN", source_symbols={YAHOO: "CDR.WA"}),
    )
    async with user_simulation(_shell(engine, FixedSearch([]), FixedHistory())) as user:
        await user.open("/")
        user.find(marker="header-search").type("projekt")
        await user.should_see("Twoje instrumenty")
        user.find(marker="own-result").click()
        await user.should_see(marker="instrument-card")

        await user.should_see(marker="header-search-message")  # the search answered and redrew the results
        gc.collect()  # a dialog goes with the element it was opened in once that is collected

        await user.should_see(marker="instrument-card")


async def _found_card(user: User, query: str) -> None:
    """Types ``query``, asks the search services with Enter and opens the first Search Result's card."""
    await user.open("/")
    user.find(marker="header-search").type(query).trigger("keydown.enter")
    await user.should_see(marker="found-result")
    user.find(marker="found-result").click()
    await user.should_see(marker="instrument-card")


async def test_a_search_result_is_added_as_an_instrument_from_its_card(engine: Engine) -> None:
    search, history = FixedSearch([VUAA]), FixedHistory()
    async with user_simulation(_shell(engine, search, history)) as user:
        await _found_card(user, "vuaa")
        await user.should_see("ISIN: IE00BFMXXD54")
        await user.should_see("Siedziba: Irlandia")
        await user.should_see("147,00 USD")

        user.find(marker="card-add").click()
        await user.should_see(marker="instrument-dialog")
        with user.scope(marker="instrument-dialog"):
            user.find(marker="instrument-class").click()
            user.find("Akcje zagraniczne").click()
            user.find("Zapisz").click()

        await user.should_see(marker="card-owned")
        await user.should_see("Dodano instrument Vanguard S&P 500 UCITS ETF USD Acc")
        [saved] = list_instruments(engine)
        assert (saved.isin, saved.quote_currency, dict(saved.source_symbols)) == (
            "IE00BFMXXD54",
            "USD",
            {YAHOO: "VUAA.L"},
        )


async def test_a_search_result_already_held_shows_it_is_owned_instead_of_the_add_button(engine: Engine) -> None:
    add_instrument(
        engine,
        InstrumentDraft("Mój VUAA", _class_id(engine, "Akcje zagraniczne"), "USD", source_symbols={YAHOO: "VUAA.L"}),
    )
    search, history = FixedSearch([VUAA]), FixedHistory()
    async with user_simulation(_shell(engine, search, history)) as user:
        await _found_card(user, "vanguard")

        await user.should_see(marker="card-owned")
        await user.should_not_see(marker="card-add")


async def test_a_search_service_failing_beside_the_others_is_noted_in_the_list(engine: Engine) -> None:
    search, history = FixedSearch([VUAA], notes=("analizy.pl nie odpowiada",)), FixedHistory()
    async with user_simulation(_shell(engine, search, history)) as user:
        await user.open("/")
        user.find(marker="header-search").type("vuaa").trigger("keydown.enter")

        await user.should_see("analizy.pl nie odpowiada")
        await user.should_see(marker="found-result")


async def test_an_own_instruments_card_shows_its_position_on_each_account(engine: Engine) -> None:
    shares = _class_id(engine, "Akcje polskie")
    cdr = add_instrument(engine, InstrumentDraft("CD Projekt", shares, "PLN", manual_price=Decimal(300))).id
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    add_transactions(
        engine,
        [
            TransactionDraft(ike, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(5000)),
            buy_or_sell(ike, date(2026, 8, 4), TransactionType.BUY, cdr, Decimal(10), Decimal(250), Decimal(0)),
        ],
    )
    search, history = FixedSearch([]), FixedHistory()
    async with user_simulation(_shell(engine, search, history)) as user:
        await user.open("/")
        user.find(marker="header-search").type("cd projekt")
        await user.should_see(marker="own-result")
        user.find(marker="own-result").click()

        await user.should_see(marker="card-position")
        await user.should_see("IKE · 10 szt. · wartość 3 000,00 zł · wynik +500,00 zł")


async def test_a_listing_without_history_says_so_on_its_card(engine: Engine) -> None:
    listing = FoundListing("CD Projekt", "CDR", "GPW", "PLN", source_symbols={BOSSA: "CDR"}, source="Yahoo")
    async with user_simulation(_shell(engine, FixedSearch([listing]), NoHistory())) as user:
        await _found_card(user, "cdr")

        await user.should_see(marker="card-no-history")


async def test_an_instrument_added_from_the_card_is_listed_at_once_in_ustawienia(engine: Engine) -> None:
    search, history = FixedSearch([VUAA]), FixedHistory()
    async with user_simulation(_shell(engine, search, history)) as user:
        await user.open("/ustawienia")
        await user.should_see("Nie dodano jeszcze żadnego instrumentu.")
        user.find(marker="header-search").type("vuaa").trigger("keydown.enter")
        await user.should_see(marker="found-result")
        user.find(marker="found-result").click()
        await user.should_see(marker="card-add")
        user.find(marker="card-add").click()
        with user.scope(marker="instrument-dialog"):
            user.find(marker="instrument-class").click()
            user.find("Akcje zagraniczne").click()
            user.find("Zapisz").click()

        await user.should_see(marker="card-owned")
        await user.should_not_see("Nie dodano jeszcze żadnego instrumentu.")
        await user.should_see(marker="edit-instrument")


async def test_enter_opens_the_highlighted_own_instrument_without_waiting_for_the_search_services(
    engine: Engine,
) -> None:
    add_instrument(
        engine,
        InstrumentDraft("CD Projekt", _class_id(engine, "Akcje polskie"), "PLN", source_symbols={YAHOO: "CDR.WA"}),
    )
    async with user_simulation(_shell(engine, FixedSearch([VUAA]), FixedHistory())) as user:
        await user.open("/")
        field = user.find(marker="header-search").type("cd")
        await user.should_see(marker="own-result")
        field.trigger("keydown.enter")

        await user.should_see(marker="instrument-card")
        await user.should_see(marker="card-edit")


class NoHistory:
    """Gives no listing any close, as for one with neither a Yahoo nor an analizy.pl symbol."""

    def closes(self, listing: FoundListing, last: date) -> list[Quote]:
        return []


async def test_an_own_instrument_without_a_live_history_shows_its_saved_quotes(engine: Engine) -> None:
    pzu = add_instrument(
        engine, InstrumentDraft("PZU", _class_id(engine, "Akcje polskie"), "PLN", source_symbols={BOSSA: "PZU"})
    ).id
    saved = [Quote(Decimal(price), "PLN", date(2026, 10, day), BOSSA) for day, price in [(19, "40"), (20, "42")]]
    save_quote_history(engine, pzu, saved, None, NOW)
    async with user_simulation(_shell(engine, FixedSearch([]), NoHistory())) as user:
        await user.open("/")
        user.find(marker="header-search").type("pzu")
        await user.should_see(marker="own-result")
        user.find(marker="own-result").click()

        await user.should_see("42,00 zł")
        await user.should_see("+5,00 %")
