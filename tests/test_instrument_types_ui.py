"""Instrument Type in Ustawienia > Instrumenty (issue #198): the form's field, the sections per Type and the search."""

from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.instruments import AssetClass, InstrumentDraft, InstrumentType
from financial_app.domain.prices import ANALIZY, YAHOO
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes, list_instruments
from financial_app.ui.shell import build_shell


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
async def user(engine: Engine) -> AsyncIterator[User]:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        yield user


def _class_named(engine: Engine, name: str) -> AssetClass:
    return next(c for c in list_asset_classes(engine) if c.name == name)


def _add(engine: Engine, name: str, class_name: str, kind: InstrumentType, **fields: object) -> None:
    draft = InstrumentDraft(name, _class_named(engine, class_name).id, "PLN", instrument_type=kind, **fields)  # type: ignore[arg-type]
    add_instrument(engine, draft)


def _title(user: User, kind: str) -> str:
    """The title of the Instrument Type's section, its expansion's label."""
    [section] = user.find(marker=f"instrument-type-{kind}").elements
    assert isinstance(section, ui.expansion)
    return str(section.text)


async def test_a_new_instrument_without_a_chosen_type_gets_one_from_its_facts(user: User, engine: Engine) -> None:
    user.find("Dodaj instrument").click()
    with user.scope(marker="instrument-dialog"):
        user.find(marker="instrument-class").click()
        user.find("Metale i surowce").click()
    user.find(marker="instrument-name").type("Krugerrand")
    user.find(marker="instrument-metal-grams").type("31,1034768")
    user.find(marker="instrument-price").type("12 000")
    user.find("Zapisz").click()

    with user.scope(marker="instruments"):
        await user.should_see("Krugerrand")
    [saved] = list_instruments(engine)
    assert saved.instrument_type is InstrumentType.METAL


async def test_the_user_changes_the_type_in_the_form(engine: Engine) -> None:
    _add(engine, "WisdomTree Gold", "Metale i surowce", InstrumentType.ETF, source_symbols={YAHOO: "PHAU.L"})
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-instrument").click()
        user.find(marker="instrument-type").click()
        with user.scope(marker="instrument-dialog"):
            user.find("ETC").click()
        user.find("Zapisz").click()

        await user.should_see(marker="instrument-type-etc")
        with user.scope(marker="instrument-type-etc"):
            await user.should_see("WisdomTree Gold")
    assert list_instruments(engine)[0].instrument_type is InstrumentType.ETC


async def test_instruments_are_listed_in_a_section_per_type_with_its_count(engine: Engine) -> None:
    _add(engine, "Xtrackers MSCI World", "Akcje zagraniczne", InstrumentType.ETF)
    _add(engine, "Beta ETF WIG20TR", "Akcje polskie", InstrumentType.ETF)
    _add(engine, "PZU Akcji", "Akcje polskie", InstrumentType.FUND, source_symbols={ANALIZY: "PZU01"})
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")

        await user.should_see(marker="instrument-type-etf")
        assert _title(user, "etf") == "ETF (2)"
        with user.scope(marker="instrument-type-etf"):
            # The elements are a set; their ids follow the order they were drawn in
            rows = [
                label.text
                for label in sorted(user.find(ui.label).elements, key=lambda element: element.id)
                if label.text in {"Beta ETF WIG20TR", "Xtrackers MSCI World"}
            ]
            # Alphabetically within the section
            assert rows == ["Beta ETF WIG20TR", "Xtrackers MSCI World"]
            await user.should_see("Akcje zagraniczne")
        assert _title(user, "fund") == "Fundusz (1)"
        with user.scope(marker="instrument-type-fund"):
            await user.should_see("PZU Akcji")
        # An empty section is hidden
        await user.should_not_see(marker="instrument-type-stock")


async def test_the_search_filters_every_section_by_name_isin_or_source_symbol(engine: Engine) -> None:
    _add(engine, "Xtrackers MSCI World", "Akcje zagraniczne", InstrumentType.ETF, isin="IE00BJ0KDQ92")
    _add(engine, "Beta ETF WIG20TR", "Akcje polskie", InstrumentType.ETF)
    _add(engine, "PZU Akcji", "Akcje polskie", InstrumentType.FUND, source_symbols={ANALIZY: "PZU01"})
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")

        await user.should_see(marker="instrument-type-etf")
        user.find(marker="instruments-search").type("pzu01")
        await user.should_not_see(marker="instrument-type-etf")
        with user.scope(marker="instrument-type-fund"):
            await user.should_see("PZU Akcji")

        user.find(marker="instruments-search").clear().type("ie00bj0")
        await user.should_see(marker="instrument-type-etf")
        assert _title(user, "etf") == "ETF (1)"
        with user.scope(marker="instrument-type-etf"):
            await user.should_see("Xtrackers MSCI World")
            await user.should_not_see("Beta ETF WIG20TR")
        await user.should_not_see(marker="instrument-type-fund")


async def test_the_type_badge_stands_beside_the_asset_class(engine: Engine) -> None:
    _add(engine, "Złoto", "Metale i surowce", InstrumentType.METAL, metal_grams=Decimal(31), manual_price=Decimal(1))
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")

        await user.should_see(marker="instrument-type-metal")
        with user.scope(marker="instrument-type-metal"):
            await user.should_see(marker="instrument-type-badge")
            await user.should_see("Metale i surowce")
