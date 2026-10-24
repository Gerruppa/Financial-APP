"""The header search and the Instrument Card (issue #175), on a test search and history without the network."""

import gc
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.formatting import NBSP
from financial_app.domain.fund_profile import FundProfile
from financial_app.domain.history import Cover
from financial_app.domain.instrument_card import CardPeriod
from financial_app.domain.instrument_search import FoundListing, FoundListings, InstrumentSearch
from financial_app.domain.instruments import InstrumentDraft, InstrumentType
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.prices import BOSSA, YAHOO, Quote
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.history import save_nbp_history, save_quote_history
from financial_app.persistence.instruments import add_instrument, list_asset_classes, list_instruments
from financial_app.persistence.transactions import add_transactions
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates
from financial_app.sources.portfolio_history import PortfolioHistory
from financial_app.ui.instrument_card import FundProfiles, ListingHistory
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


class FixedProfiles:
    """Gives every symbol the same ``profile`` (by default none), recording the symbols asked."""

    def __init__(self, profile: FundProfile | None = None) -> None:
        self.profile_given = profile
        self.asked: list[str] = []

    def profile(self, symbol: str) -> FundProfile | None:
        self.asked.append(symbol)
        return self.profile_given


def _shell(
    engine: Engine,
    search: InstrumentSearch,
    history: ListingHistory,
    profiles: FundProfiles | None = None,
    rates: NbpRates | None = None,
) -> Callable[[], None]:
    """The window on ``search``, the card's ``history`` and fund ``profiles`` (none by default), its History
    computed inline rather than in the process pool, with no Quotes fetched, and ``rates`` (by default NBP's)."""
    quotes = QuoteHistory(engine, lambda url: "Brak danych", lambda: TODAY, lambda: NOW, lambda url: None)
    portfolio = PortfolioHistory(engine, quotes, NbpRates(engine), lambda: TODAY, _inline)
    fund_profiles = profiles or FixedProfiles()
    return lambda: build_shell(
        engine,
        rates,
        now=lambda: NOW,
        search=search,
        card_history=history,
        history=portfolio,
        fund_profiles=fund_profiles,
    )


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


async def test_a_chart_period_chosen_redraws_the_chart_from_its_start(engine: Engine) -> None:
    async with user_simulation(_shell(engine, FixedSearch([VUAA]), FixedHistory())) as user:
        await _found_card(user, "vuaa")
        await user.should_see(marker="chart-price")
        [toggle] = user.find(marker="card-periods").elements
        assert isinstance(toggle, ui.toggle)
        assert [str(period) for period in toggle.options] == ["YTD", "1M", "3M", "6M", "1R", "3L", "5L", "Max"]

        toggle.value = CardPeriod.ONE_MONTH  # as the browser's choice maps back to its option

        await user.should_see(marker="chart-price")
        [chart] = user.find(marker="chart-price").elements
        assert isinstance(chart, ui.echart)
        assert chart.options["xAxis"]["data"] == ["31.12.2025", "19.10.2026", "20.10.2026"]


def _save_rates(engine: Engine, currency: str, rate: str) -> None:
    """One NBP Rate from 20.12.2025, with days to TODAY covered, so that the card fetches none."""
    days = Cover(date(2025, 12, 1), TODAY)
    save_nbp_history(engine, currency, [NbpRate(currency, Decimal(rate), date(2025, 12, 20), "1/A/NBP/2025")], days)


async def test_the_chart_currency_chosen_converts_the_prices_at_nbp_rates(engine: Engine) -> None:
    _save_rates(engine, "USD", "4")
    _save_rates(engine, "EUR", "5")
    rates = NbpRates(engine, today=lambda: TODAY)
    async with user_simulation(_shell(engine, FixedSearch([VUAA]), FixedHistory(), rates=rates)) as user:
        await _found_card(user, "vuaa")
        await user.should_see(marker="card-currency")
        [select] = user.find(marker="card-currency").elements
        assert isinstance(select, ui.select)
        assert select.value == "USD" and select.options == ["USD", "PLN", "EUR"]

        select.value = "EUR"

        await user.should_see(marker="card-converted")
        await user.should_see(f"117,60{NBSP}EUR")  # 147 USD * 4 / 5
        [chart] = user.find(marker="chart-price").elements
        assert isinstance(chart, ui.echart)
        assert chart.options["series"][0]["data"][-1] == pytest.approx(117.6)


async def test_a_currency_without_nbp_rates_is_noted_and_the_quote_currency_stays(engine: Engine) -> None:
    def no_network(url: str) -> str | None:
        raise OSError

    rates = NbpRates(engine, no_network, lambda: TODAY)
    async with user_simulation(_shell(engine, FixedSearch([VUAA]), FixedHistory(), rates=rates)) as user:
        await _found_card(user, "vuaa")
        await user.should_see(marker="card-currency")
        [select] = user.find(marker="card-currency").elements
        assert isinstance(select, ui.select)
        select.value = "PLN"
        await user.should_see("Nie udało się pobrać kursów NBP USD")
        await user.should_not_see(marker="card-converted")


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


async def test_the_card_shows_the_instrument_type_a_search_told_and_adding_keeps_it(engine: Engine) -> None:
    etf = replace(VUAA, instrument_type=InstrumentType.ETF)
    async with user_simulation(_shell(engine, FixedSearch([etf]), FixedHistory())) as user:
        await _found_card(user, "vuaa")
        with user.scope(marker="instrument-card"):
            await user.should_see(marker="card-instrument-type")

        user.find(marker="card-add").click()
        await user.should_see(marker="instrument-dialog")
        with user.scope(marker="instrument-dialog"):
            user.find(marker="instrument-class").click()
            user.find("Akcje zagraniczne").click()
            user.find("Zapisz").click()

        await user.should_see(marker="card-owned")
    [saved] = list_instruments(engine)
    assert saved.instrument_type is InstrumentType.ETF


PROFILE = FundProfile(Decimal("0.2"), Decimal("88972738560"), "USD", "Vanguard Group (Ireland) Limited")


async def test_the_card_shows_the_fund_profile_marked_as_from_yahoo(engine: Engine) -> None:
    profiles = FixedProfiles(PROFILE)
    async with user_simulation(_shell(engine, FixedSearch([VUAA]), FixedHistory(), profiles)) as user:
        await _found_card(user, "vuaa")

        await user.should_see(f"TER: 0,20{NBSP}% (Yahoo)")
        await user.should_see(f"Wielkość funduszu: 88,97{NBSP}mld{NBSP}USD (wg Yahoo)")
        await user.should_see("Emitent: Vanguard Group (Ireland) Limited (wg Yahoo)")
    assert profiles.asked == ["VUAA.L"]


async def test_the_card_shows_no_profile_section_when_none_comes_or_for_a_warsaw_listing(engine: Engine) -> None:
    warsaw = replace(VUAA, symbol="ETFBW20TR.WA", source_symbols={YAHOO: "ETFBW20TR.WA"})
    profiles = FixedProfiles(PROFILE)
    async with user_simulation(_shell(engine, FixedSearch([warsaw]), FixedHistory(), profiles)) as user:
        await _found_card(user, "etf")
        await user.should_see(marker="chart-price")

        await user.should_not_see(marker="card-profile")
    assert profiles.asked == []


async def test_the_card_has_no_profile_section_without_a_profile(engine: Engine) -> None:
    async with user_simulation(_shell(engine, FixedSearch([VUAA]), FixedHistory())) as user:
        await _found_card(user, "vuaa")
        await user.should_see(marker="chart-price")

        await user.should_not_see(marker="card-profile")


async def test_an_instruments_own_ter_wins_over_yahoos(engine: Engine) -> None:
    add_instrument(
        engine,
        InstrumentDraft(
            "Vanguard S&P 500",
            _class_id(engine, "Akcje zagraniczne"),
            "USD",
            source_symbols={YAHOO: "VUAA.L"},
            ter_percent=Decimal("0.07"),
            instrument_type=InstrumentType.ETF,
        ),
    )
    async with user_simulation(_shell(engine, FixedSearch([]), FixedHistory(), FixedProfiles(PROFILE))) as user:
        await user.open("/")
        user.find(marker="header-search").type("vanguard")
        await user.should_see(marker="own-result")
        user.find(marker="own-result").click()

        await user.should_see(f"TER: 0,07{NBSP}%")
        await user.should_see(f"Wielkość funduszu: 88,97{NBSP}mld{NBSP}USD (wg Yahoo)")
        await user.should_not_see("(Yahoo)")


async def test_adding_a_search_result_fills_the_empty_ter_from_yahoo(engine: Engine) -> None:
    async with user_simulation(_shell(engine, FixedSearch([VUAA]), FixedHistory(), FixedProfiles(PROFILE))) as user:
        await _found_card(user, "vuaa")
        await user.should_see(f"TER: 0,20{NBSP}% (Yahoo)")

        user.find(marker="card-add").click()
        await user.should_see(marker="instrument-dialog")
        with user.scope(marker="instrument-dialog"):
            user.find(marker="instrument-class").click()
            user.find("Akcje zagraniczne").click()
            user.find("Zapisz").click()

        await user.should_see(marker="card-owned")
    [saved] = list_instruments(engine)
    assert saved.ter_percent == Decimal("0.2")
