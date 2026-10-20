"""Searching an Instrument by ISIN, name or symbol in the Instrument dialog (issue #25), on saved Yahoo responses."""

from collections.abc import AsyncIterator
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.instrument_search import CombinedSearch, FoundListing, InstrumentSearchError
from financial_app.domain.instruments import DistributionPolicy, InstrumentDraft
from financial_app.domain.prices import ANALIZY, BOSSA, YAHOO
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import (
    add_instrument,
    list_asset_classes,
    list_instruments,
    update_asset_class,
)
from financial_app.sources.yahoo import YahooSearch
from financial_app.ui.shell import build_shell

FIXTURES = Path(__file__).parent / "fixtures" / "yahoo"


def _saved(url: str) -> str | None:
    """The saved search or chart response for ``url``, as in test_yahoo_search."""
    parsed = urlparse(url)
    if "/search" in parsed.path:
        path = FIXTURES / "search" / f"{parse_qs(parsed.query)['q'][0].replace(' ', '_')}.json"
        return path.read_text(encoding="utf-8") if path.is_file() else '{"count": 0, "quotes": []}'
    path = FIXTURES / f"{unquote(parsed.path.split('/chart/')[1])}.json"
    return path.read_text(encoding="utf-8") if path.is_file() else None


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
async def user(engine: Engine) -> AsyncIterator[User]:
    async with user_simulation(lambda: build_shell(engine, search=YahooSearch(_saved))) as user:
        await user.open("/ustawienia")
        yield user


def _class_id(engine: Engine, name: str) -> int:
    return next(c.id for c in list_asset_classes(engine) if c.name == name)


def _value(user: User, marker: str) -> str:
    [field] = user.find(marker=marker).elements
    assert isinstance(field, ui.input)
    return str(field.value)


async def _search(user: User, query: str) -> None:
    user.find(marker="instrument-search").clear().type(query)
    user.find(marker="instrument-search-button").click()


async def test_an_isin_shows_its_listings_and_a_choice_fills_the_empty_fields(user: User, engine: Engine) -> None:
    user.find("Dodaj instrument").click()
    await _search(user, "IE00B6R52259")

    for symbol in ["ISAC.L", "IUSQ.DE", "SSAC.L", "SSAC.SW", "SSAC.AS", "ISAC.MI"]:
        await user.should_see(marker=f"search-result-{symbol}")
    user.find(marker="search-result-IUSQ.DE").click()

    assert _value(user, "instrument-isin") == "IE00B6R52259"
    assert _value(user, "instrument-currency") == "EUR"
    assert _value(user, "instrument-market") == "XETRA"
    assert _value(user, "instrument-symbol-yahoo") == "IUSQ.DE"
    assert _value(user, "instrument-symbol-bossa") == ""
    # An empty name is filled with the listing's
    assert _value(user, "instrument-name") == "iShares MSCI All Country World UCITS ETF USD Acc"

    with user.scope(marker="instrument-dialog"):
        user.find(marker="instrument-class").click()
        user.find("Akcje zagraniczne").click()
    user.find("Zapisz").click()

    [saved] = list_instruments(engine)
    assert (saved.isin, saved.quote_currency, saved.market) == ("IE00B6R52259", "EUR", "XETRA")
    assert saved.source_symbols == {YAHOO: "IUSQ.DE"}
    # An ETF's domicile comes from its ISIN and its distribution policy from its name
    assert (saved.domicile, saved.distribution_policy) == ("Irlandia", DistributionPolicy.ACCUMULATING)


async def test_a_warsaw_result_fills_the_yahoo_and_bossa_symbols(user: User) -> None:
    user.find("Dodaj instrument").click()
    await _search(user, "cd projekt")
    await user.should_see(marker="search-result-CDR.WA")
    user.find(marker="search-result-CDR.WA").click()

    assert (_value(user, "instrument-symbol-yahoo"), _value(user, "instrument-symbol-bossa")) == ("CDR.WA", "CDR")
    assert _value(user, "instrument-market") == "GPW"


async def test_values_already_entered_and_the_name_are_kept(engine: Engine) -> None:
    etfs = _class_id(engine, "Akcje zagraniczne")
    add_instrument(engine, InstrumentDraft("Mój ACWI", etfs, "USD", "LSE", source_symbols={BOSSA: "X"}))

    async with user_simulation(lambda: build_shell(engine, search=YahooSearch(_saved))) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-instrument").click()
        await _search(user, "IE00B6R52259")
        await user.should_see(marker="search-result-IUSQ.DE")
        user.find(marker="search-result-IUSQ.DE").click()

        assert _value(user, "instrument-name") == "Mój ACWI"
        assert _value(user, "instrument-currency") == "USD"
        assert _value(user, "instrument-market") == "LSE"
        assert _value(user, "instrument-symbol-bossa") == "X"
        assert _value(user, "instrument-symbol-yahoo") == "IUSQ.DE"
        assert _value(user, "instrument-isin") == "IE00B6R52259"


async def test_an_instrument_without_source_symbols_is_searched_by_its_name(engine: Engine) -> None:
    add_instrument(engine, InstrumentDraft("ISAC", _class_id(engine, "Akcje zagraniczne"), "USD"))

    async with user_simulation(lambda: build_shell(engine, search=YahooSearch(_saved))) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-instrument").click()

        assert _value(user, "instrument-search") == "ISAC"


async def test_a_new_instruments_default_pln_is_replaced_by_the_listings_currency(user: User) -> None:
    user.find("Dodaj instrument").click()
    assert _value(user, "instrument-currency") == "PLN"
    await _search(user, "IE00B6R52259")
    await user.should_see(marker="search-result-ISAC.L")
    user.find(marker="search-result-ISAC.L").click()

    assert _value(user, "instrument-currency") == "USD"


async def test_without_network_the_search_says_so_and_the_form_still_saves(engine: Engine) -> None:
    def offline(url: str) -> str | None:
        raise URLError("offline")

    async with user_simulation(lambda: build_shell(engine, search=YahooSearch(offline))) as user:
        await user.open("/ustawienia")
        user.find("Dodaj instrument").click()
        await _search(user, "ISAC")
        await user.should_see("Nie udało się połączyć z Yahoo")

        user.find(marker="instrument-name").type("PZU")
        with user.scope(marker="instrument-dialog"):
            user.find(marker="instrument-class").click()
            user.find("Akcje polskie").click()
        user.find("Zapisz").click()

        await user.should_see(marker="edit-instrument")
        assert [i.name for i in list_instruments(engine)] == ["PZU"]


async def test_nothing_found_says_so(user: User) -> None:
    user.find("Dodaj instrument").click()
    await _search(user, "PLFIO0000014")

    await user.should_see("Nic nie znaleziono")


def _chosen_class(user: User) -> object:
    [field] = user.find(marker="instrument-class").elements
    assert isinstance(field, ui.select)
    return field.value


async def test_a_result_sets_an_empty_class_and_shows_its_fields(user: User, engine: Engine) -> None:
    user.find("Dodaj instrument").click()
    await _search(user, "cd projekt")
    await user.should_see(marker="search-result-CDR.WA")
    user.find(marker="search-result-CDR.WA").click()

    assert _chosen_class(user) == _class_id(engine, "Akcje polskie")
    with user.scope(marker="class-sources"):
        await user.should_see("Symbol Bossa")


async def test_a_class_already_chosen_is_kept(user: User, engine: Engine) -> None:
    user.find("Dodaj instrument").click()
    with user.scope(marker="instrument-dialog"):
        user.find(marker="instrument-class").click()
        user.find("Multi-asset").click()
    await _search(user, "cd projekt")
    await user.should_see(marker="search-result-CDR.WA")
    user.find(marker="search-result-CDR.WA").click()

    assert _chosen_class(user) == _class_id(engine, "Multi-asset")


async def test_a_class_the_user_does_not_have_is_not_set(user: User, engine: Engine) -> None:
    stocks = next(c for c in list_asset_classes(engine) if c.name == "Akcje polskie")
    update_asset_class(engine, stocks.id, "Spółki GPW", stocks.fallback_order)
    user.find("Dodaj instrument").click()
    await _search(user, "cd projekt")
    await user.should_see(marker="search-result-CDR.WA")
    user.find(marker="search-result-CDR.WA").click()

    assert _chosen_class(user) is None


# Yahoo and analizy.pl searched together (issue #60)


class FakeSearch:
    def __init__(self, results: list[FoundListing] | None = None, error: str = "") -> None:
        self.results = results or []
        self.error = error

    def search(self, query: str) -> list[FoundListing]:
        if self.error:
            raise InstrumentSearchError(self.error)
        return self.results


PZU60 = FoundListing(
    name="PPK inPZU 2060",
    symbol="PZU60",
    market="",
    currency="PLN",
    source_symbols={ANALIZY: "PZU60"},
    asset_class="Multi-asset",
)
PZU = FoundListing("PZU SA", "PZU.WA", "GPW", "PLN", {YAHOO: "PZU.WA", BOSSA: "PZU"}, asset_class="Akcje polskie")


async def test_both_searches_results_are_listed_with_their_source(engine: Engine) -> None:
    combined = CombinedSearch({"Yahoo": FakeSearch([PZU]), "analizy.pl": FakeSearch([PZU60])})

    async with user_simulation(lambda: build_shell(engine, search=combined)) as user:
        await user.open("/ustawienia")
        user.find("Dodaj instrument").click()
        await _search(user, "PZU")
        await user.should_see(marker="search-result-PZU60")

        with user.scope(marker="search-result-PZU.WA"):
            await user.should_see("Yahoo")
        with user.scope(marker="search-result-PZU60"):
            await user.should_see("analizy.pl")
        user.find(marker="search-result-PZU60").click()

        assert _value(user, "instrument-symbol-analizy") == "PZU60"
        assert _chosen_class(user) == _class_id(engine, "Multi-asset")
        with user.scope(marker="class-sources"):
            await user.should_see("Kod funduszu")


async def test_a_search_that_does_not_answer_is_noted_beside_the_others_results(engine: Engine) -> None:
    combined = CombinedSearch({"Yahoo": FakeSearch([PZU]), "analizy.pl": FakeSearch(error="Brak sieci.")})

    async with user_simulation(lambda: build_shell(engine, search=combined)) as user:
        await user.open("/ustawienia")
        user.find("Dodaj instrument").click()
        await _search(user, "PZU")

        await user.should_see(marker="search-result-PZU.WA")
        await user.should_see("analizy.pl nie odpowiada")


async def test_a_search_that_does_not_answer_is_noted_when_the_other_finds_nothing(engine: Engine) -> None:
    combined = CombinedSearch({"Yahoo": FakeSearch([]), "analizy.pl": FakeSearch(error="Brak sieci.")})

    async with user_simulation(lambda: build_shell(engine, search=combined)) as user:
        await user.open("/ustawienia")
        user.find("Dodaj instrument").click()
        await _search(user, "PZU")

        await user.should_see("Nic nie znaleziono.")
        await user.should_see("analizy.pl nie odpowiada")


async def test_an_entered_name_domicile_and_policy_are_kept(engine: Engine) -> None:
    add_instrument(
        engine,
        InstrumentDraft(
            "Mój ACWI",
            _class_id(engine, "Akcje zagraniczne"),
            "USD",
            domicile="Luksemburg",
            distribution_policy=DistributionPolicy.DISTRIBUTING,
        ),
    )

    async with user_simulation(lambda: build_shell(engine, search=YahooSearch(_saved))) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-instrument").click()
        await _search(user, "IE00B6R52259")
        await user.should_see(marker="search-result-ISAC.L")
        user.find(marker="search-result-ISAC.L").click()
        user.find("Zapisz").click()
        await user.should_not_see(marker="instrument-dialog")

    [saved] = list_instruments(engine)
    assert (saved.name, saved.domicile, saved.distribution_policy) == (
        "Mój ACWI",
        "Luksemburg",
        DistributionPolicy.DISTRIBUTING,
    )
