"""Saving Asset Classes and Instruments in SQLite (issue #12)."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.instruments import AssetClass, InstrumentDraft, InstrumentError
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import (
    add_asset_class,
    add_instrument,
    list_asset_classes,
    list_instruments,
    rename_asset_class,
    update_instrument,
)

SHEET_ASSET_CLASSES = [
    "Gotówka",
    "Akcje polskie",
    "Akcje zagraniczne",
    "Obligacje skarbowe polskie",
    "Obligacje skarbowe zagraniczne",
    "Obligacje korporacyjne polskie",
    "Obligacje korporacyjne zagraniczne",
    "Metale i surowce",
    "Kryptowaluty",
    "Waluty",
    "Inne",
    "Multi-asset",
]


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    return tmp_path / "app.sqlite3"


@pytest.fixture
def engine(db_file: Path) -> Engine:
    return init_db(db_file)


def _class_named(engine: Engine, name: str) -> AssetClass:
    return next(c for c in list_asset_classes(engine) if c.name == name)


def test_new_database_starts_with_the_twelve_asset_classes_of_the_sheet(engine: Engine) -> None:
    assert [c.name for c in list_asset_classes(engine)] == SHEET_ASSET_CLASSES


def test_added_asset_class_goes_to_the_end_of_the_list(engine: Engine) -> None:
    added = add_asset_class(engine, " Nieruchomości ")

    assert added.name == "Nieruchomości"
    assert list_asset_classes(engine)[-1] == added


def test_asset_class_names_are_unique_ignoring_case(engine: Engine) -> None:
    with pytest.raises(InstrumentError, match="już istnieje"):
        add_asset_class(engine, "akcje POLSKIE")
    with pytest.raises(InstrumentError, match="już istnieje"):
        rename_asset_class(engine, _class_named(engine, "Inne").id, "GOTÓWKA")


def test_renaming_an_asset_class_keeps_its_place(engine: Engine) -> None:
    other = _class_named(engine, "Inne")

    rename_asset_class(engine, other.id, "Pozostałe")

    names = [c.name for c in list_asset_classes(engine)]
    assert names[10] == "Pozostałe"
    assert "Inne" not in names


def test_renamed_asset_class_shows_at_every_instrument_of_that_class(engine: Engine) -> None:
    polish_stocks = _class_named(engine, "Akcje polskie")
    add_instrument(engine, InstrumentDraft("PZU", polish_stocks.id, "PLN", "GPW"))
    add_instrument(engine, InstrumentDraft("PKN Orlen", polish_stocks.id, "PLN", "GPW"))
    add_instrument(engine, InstrumentDraft("Apple", _class_named(engine, "Akcje zagraniczne").id, "USD", "NASDAQ"))

    rename_asset_class(engine, polish_stocks.id, "Akcje GPW")

    classes = {i.name: i.asset_class_name for i in list_instruments(engine)}
    assert classes == {"PZU": "Akcje GPW", "PKN Orlen": "Akcje GPW", "Apple": "Akcje zagraniczne"}


def test_added_instrument_survives_restart(db_file: Path, engine: Engine) -> None:
    metals = _class_named(engine, "Metale i surowce")
    draft = InstrumentDraft("Złota moneta 1 oz", metals.id, "PLN", "", Decimal("12850.50"))
    added = add_instrument(engine, draft)
    engine.dispose()

    [saved] = list_instruments(init_db(db_file))

    assert saved == added
    assert saved.manual_price == Decimal("12850.50")
    assert saved.asset_class_name == "Metale i surowce"


def test_instruments_are_listed_by_name(engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje polskie").id
    for name in ("PZU", "allegro", "Żabka", "CD Projekt"):
        add_instrument(engine, InstrumentDraft(name, stocks, "PLN"))

    assert [i.name for i in list_instruments(engine)] == ["allegro", "CD Projekt", "PZU", "Żabka"]


def test_user_edits_an_instrument_and_gives_it_a_manual_price(engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje zagraniczne")
    etfs = _class_named(engine, "Multi-asset")
    added = add_instrument(engine, InstrumentDraft("VWCE", stocks.id, "EUR", "XETRA"))

    updated = update_instrument(
        engine, added.id, InstrumentDraft("Vanguard FTSE All-World", etfs.id, "EUR", "XETRA", Decimal("135.42"))
    )

    assert list_instruments(engine) == [updated]
    assert updated.manual_price == Decimal("135.42")
    assert updated.asset_class_name == "Multi-asset"


def test_manual_price_can_be_cleared(engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje polskie").id
    added = add_instrument(engine, InstrumentDraft("PZU", stocks, "PLN", manual_price=Decimal("45.1")))

    update_instrument(engine, added.id, replace(added, manual_price=None))

    assert list_instruments(engine)[0].manual_price is None


def test_instrument_names_are_unique_ignoring_case(engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje polskie").id
    add_instrument(engine, InstrumentDraft("Żabka", stocks, "PLN"))
    other = add_instrument(engine, InstrumentDraft("PZU", stocks, "PLN"))

    with pytest.raises(InstrumentError, match="już istnieje"):
        add_instrument(engine, InstrumentDraft("ŻABKA", stocks, "PLN"))
    with pytest.raises(InstrumentError, match="już istnieje"):
        update_instrument(engine, other.id, InstrumentDraft("żabka", stocks, "PLN"))
    assert len(list_instruments(engine)) == 2


def test_instrument_with_an_unknown_asset_class_is_rejected(engine: Engine) -> None:
    with pytest.raises(InstrumentError, match="klasa aktywów nie istnieje"):
        add_instrument(engine, InstrumentDraft("PZU", 999, "PLN"))
