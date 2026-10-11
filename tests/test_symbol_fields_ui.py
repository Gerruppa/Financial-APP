"""The Instrument dialog's Source Symbol fields laid out by the Asset Class's Fallback Order (issue #57, spec #56):
the class's sources first, the rest under "Więcej źródeł", Stooq under "Historia notowań (Stooq)"."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.instrument_search import SearchResult
from financial_app.domain.instruments import AssetClass, InstrumentDraft
from financial_app.domain.prices import ANALIZY, BANKIER, BOSSA, STOOQ, YAHOO, Quote
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import (
    add_asset_class,
    add_instrument,
    list_asset_classes,
    list_instruments,
    set_fallback_order,
)
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
FRIDAY = date(2026, 10, 9)


class FakeSource:
    def __init__(self, name: str, prices: dict[str, str]) -> None:
        self.name = name
        self.prices = prices

    def new_refresh(self) -> None:
        pass

    def quote(self, symbol: str, currency: str) -> Quote:
        return Quote(Decimal(self.prices[symbol]), currency, FRIDAY, self.name)


class FakeSearch:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results

    def search(self, query: str) -> list[SearchResult]:
        return self.results


SOURCES = {BOSSA: FakeSource(BOSSA, {"PZU": "69.82"})}
PZU = SearchResult("PZU SA", "PZU.WA", "WSE", "PLN", {YAHOO: "PZU.WA", BOSSA: "PZU"})


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _class_named(engine: Engine, name: str) -> AssetClass:
    return next(c for c in list_asset_classes(engine) if c.name == name)


def _choose_asset_class(user: User, name: str) -> None:
    # Scoped to the dialog, because the Klasy aktywów list on the page shows the same names
    with user.scope(marker="instrument-dialog"):
        user.find(marker="instrument-class").click()
        user.find(name).click()


def _fields_in(user: User, section: str) -> list[str]:
    """The sources whose Source Symbol fields stand in ``section``, top to bottom."""
    (container,) = user.find(marker=section).elements
    sources = {
        element: source
        for source in (YAHOO, BOSSA, ANALIZY, BANKIER, STOOQ)
        for element in user.find(marker=f"instrument-symbol-{source}").elements
    }
    return [sources[element] for element in container.descendants() if element in sources]


async def _edit(engine: Engine, user: User) -> None:
    await user.open("/ustawienia")
    user.find(marker="edit-instrument").click()


async def test_the_classs_sources_come_first_in_its_order_and_the_rest_under_more_sources(engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje polskie")
    add_instrument(engine, InstrumentDraft("PZU", stocks.id, "PLN", source_symbols={BOSSA: "PZU"}))

    async with user_simulation(lambda: build_shell(engine, sources={})) as user:
        await _edit(engine, user)

        assert _fields_in(user, "class-sources") == [BOSSA, YAHOO]
        assert _fields_in(user, "more-sources") == [ANALIZY, BANKIER]
        assert _fields_in(user, "stooq-history") == [STOOQ]
        await user.should_see("Historia notowań (Stooq)")


async def test_a_changed_order_in_settings_changes_the_dialog(engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje polskie")
    set_fallback_order(engine, stocks.id, [YAHOO, ANALIZY])
    add_instrument(engine, InstrumentDraft("PZU", stocks.id, "PLN"))

    async with user_simulation(lambda: build_shell(engine, sources={})) as user:
        await _edit(engine, user)

        assert _fields_in(user, "class-sources") == [YAHOO, ANALIZY]
        assert _fields_in(user, "more-sources") == [BOSSA, BANKIER]


async def test_more_sources_counts_its_filled_symbols_and_they_are_saved(engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje polskie")
    add_instrument(engine, InstrumentDraft("PZU", stocks.id, "PLN", source_symbols={BOSSA: "PZU", ANALIZY: "PZU1"}))

    async with user_simulation(lambda: build_shell(engine, sources={})) as user:
        await _edit(engine, user)
        await user.should_see("Więcej źródeł (1 wypełniony)")

        user.find(marker="instrument-symbol-bankier").type("PZU2")
        await user.should_see("Więcej źródeł (2 wypełnione)")
        user.find("Zapisz").click()
        await user.should_not_see(marker="instrument-dialog")

    assert list_instruments(engine)[0].source_symbols == {BOSSA: "PZU", ANALIZY: "PZU1", BANKIER: "PZU2"}


async def test_a_new_instrument_without_a_class_shows_a_hint_instead_of_fields(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine, sources={})) as user:
        await user.open("/ustawienia")
        user.find("Dodaj instrument").click()

        with user.scope(marker="class-sources"):
            await user.should_see("Wybierz klasę aktywów, żeby zobaczyć źródła wycen")
        assert _fields_in(user, "class-sources") == []


@pytest.mark.parametrize(
    ("class_name", "note"),
    [
        ("Obligacje skarbowe polskie", "etapie 3"),
        ("Gotówka", "cenę ręczną"),
        ("Waluty", "cenę ręczną"),
        ("Własna klasa", "Ustawienia > Klasy aktywów"),
    ],
)
async def test_a_class_without_sources_says_where_the_price_comes_from(
    engine: Engine, class_name: str, note: str
) -> None:
    if class_name == "Własna klasa":
        add_asset_class(engine, class_name, [])

    async with user_simulation(lambda: build_shell(engine, sources={})) as user:
        await user.open("/ustawienia")
        user.find("Dodaj instrument").click()
        _choose_asset_class(user, class_name)

        with user.scope(marker="class-sources"):
            await user.should_see(note)
        assert _fields_in(user, "class-sources") == []
        assert _fields_in(user, "more-sources") == [YAHOO, BOSSA, ANALIZY, BANKIER]


async def test_changing_the_class_moves_the_fields_and_keeps_values_and_checks(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine, sources=SOURCES)) as user:
        await user.open("/ustawienia")
        user.find("Dodaj instrument").click()
        _choose_asset_class(user, "Akcje polskie")
        user.find(marker="instrument-symbol-bossa").type("PZU")
        user.find(marker="check-symbol-bossa").click()
        with user.scope(marker="symbol-check-bossa"):
            await user.should_see(f"69,82{NBSP}zł · 09.10.2026")

        _choose_asset_class(user, "Akcje zagraniczne")

        assert _fields_in(user, "class-sources") == [YAHOO, BOSSA]
        with user.scope(marker="class-sources"):
            await user.should_see("PZU")
        with user.scope(marker="symbol-check-bossa"):
            await user.should_see(f"69,82{NBSP}zł · 09.10.2026")


async def test_the_search_fills_fields_that_are_not_shown(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine, sources={}, search=FakeSearch([PZU]))) as user:
        await user.open("/ustawienia")
        user.find("Dodaj instrument").click()
        user.find(marker="instrument-search").type("PZU")
        user.find(marker="instrument-search-button").click()
        await user.should_see(marker="search-result-PZU.WA")
        user.find(marker="search-result-PZU.WA").click()
        await user.should_see("Więcej źródeł (2 wypełnione)")

        user.find(marker="instrument-name").type("PZU")
        _choose_asset_class(user, "Akcje polskie")
        user.find("Zapisz").click()

    assert list_instruments(engine)[0].source_symbols == {YAHOO: "PZU.WA", BOSSA: "PZU"}
