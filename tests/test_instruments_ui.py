"""Ustawienia > Klasy aktywów and Instrumenty (issue #12), run without a browser."""

from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.instruments import AssetClass, InstrumentDraft
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


def _fill_form(user: User, **fields: str) -> None:
    for marker, text in fields.items():
        user.find(marker=marker).clear().type(text)


def _choose_asset_class(user: User, name: str) -> None:
    # Scoped to the dialog, because the Klasy aktywów list on the page shows the same names
    with user.scope(marker="instrument-dialog"):
        user.find(marker="instrument-class").click()
        user.find(name).click()


async def test_settings_list_the_seeded_asset_classes(user: User) -> None:
    with user.scope(marker="asset-classes"):
        await user.should_see("Gotówka")
        await user.should_see("Obligacje korporacyjne zagraniczne")
        await user.should_see("Multi-asset")


async def test_user_adds_an_asset_class(user: User, engine: Engine) -> None:
    user.find("Dodaj klasę").click()
    _fill_form(user, **{"asset-class-name": "Nieruchomości"})
    user.find("Zapisz").click()

    with user.scope(marker="asset-classes"):
        await user.should_see("Nieruchomości")
    assert list_asset_classes(engine)[-1].name == "Nieruchomości"


async def test_renamed_asset_class_shows_at_its_instruments(engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje polskie")
    add_instrument(engine, InstrumentDraft("PZU", stocks.id, "PLN", "GPW"))

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker=f"edit-asset-class-{stocks.id}").click()
        _fill_form(user, **{"asset-class-name": "Akcje GPW"})
        user.find("Zapisz").click()

        with user.scope(marker="instruments"):
            await user.should_see("Akcje GPW")
            await user.should_not_see("Akcje polskie")


async def test_duplicate_asset_class_name_is_reported(user: User, engine: Engine) -> None:
    user.find("Dodaj klasę").click()
    _fill_form(user, **{"asset-class-name": "inne"})
    user.find("Zapisz").click()

    await user.should_see("już istnieje")
    assert len(list_asset_classes(engine)) == 12


async def test_user_adds_an_instrument_with_a_manual_price(user: User, engine: Engine) -> None:
    user.find("Dodaj instrument").click()
    _choose_asset_class(user, "Metale i surowce")
    _fill_form(
        user,
        **{
            "instrument-name": "Złota moneta 1 oz",
            "instrument-currency": "pln",
            "instrument-market": "Mennica",
            "instrument-price": "12 850,5",
        },
    )
    user.find("Zapisz").click()

    with user.scope(marker="instruments"):
        await user.should_see("Złota moneta 1 oz")
        await user.should_see("12\xa0850,50 PLN")
    [saved] = list_instruments(engine)
    assert saved.asset_class_name == "Metale i surowce"
    assert saved.manual_price == Decimal("12850.5")
    assert (saved.quote_currency, saved.market) == ("PLN", "Mennica")


async def test_user_edits_an_instrument(engine: Engine) -> None:
    add_instrument(engine, InstrumentDraft("VWCE", _class_named(engine, "Akcje zagraniczne").id, "EUR", "XETRA"))

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-instrument").click()
        _choose_asset_class(user, "Multi-asset")
        _fill_form(user, **{"instrument-price": "135,42"})
        user.find("Zapisz").click()

        with user.scope(marker="instruments"):
            await user.should_see("135,42 EUR")
    [saved] = list_instruments(engine)
    assert saved.asset_class_name == "Multi-asset"
    assert saved.manual_price == Decimal("135.42")


async def test_invalid_manual_price_is_reported_and_not_saved(user: User, engine: Engine) -> None:
    user.find("Dodaj instrument").click()
    _fill_form(user, **{"instrument-name": "PZU", "instrument-price": "abc"})
    user.find("Zapisz").click()

    await user.should_see("Cena ręczna musi być liczbą")
    assert list_instruments(engine) == []
