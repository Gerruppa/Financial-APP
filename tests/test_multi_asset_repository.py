"""Saving Multi-asset Splits with their Instruments (issue #75)."""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.instruments import AssetClass, Instrument, InstrumentDraft, InstrumentError
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import (
    add_asset_class,
    add_instrument,
    delete_asset_class,
    delete_instrument,
    list_asset_classes,
    list_instruments,
    rename_asset_class,
    set_multi_asset_split,
    update_instrument,
)
from financial_app.persistence.reset import clear_portfolio


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    return tmp_path / "app.sqlite3"


@pytest.fixture
def engine(db_file: Path) -> Engine:
    return init_db(db_file)


def _class_named(engine: Engine, name: str) -> AssetClass:
    return next(c for c in list_asset_classes(engine) if c.name == name)


def _vanguard(engine: Engine, split: dict[int, Decimal] | None = None) -> Instrument:
    multi = _class_named(engine, "Multi-asset").id
    return add_instrument(
        engine, InstrumentDraft("Vanguard LifeStrategy 80", multi, "EUR", multi_asset_split=split or {})
    )


def _two_classes(engine: Engine) -> dict[int, Decimal]:
    stocks = _class_named(engine, "Akcje zagraniczne").id
    bonds = _class_named(engine, "Obligacje skarbowe zagraniczne").id
    return {stocks: Decimal("79.5"), bonds: Decimal("20.5")}


def test_a_split_is_kept_exactly_with_its_class_names_after_restart(db_file: Path, engine: Engine) -> None:
    split = _two_classes(engine)
    added = _vanguard(engine, split)
    engine.dispose()

    [saved] = list_instruments(init_db(db_file))

    assert saved == added
    assert saved.multi_asset_split == split
    assert sorted(saved.split_class_names.values()) == ["Akcje zagraniczne", "Obligacje skarbowe zagraniczne"]


def test_the_split_follows_the_order_of_the_asset_classes(engine: Engine) -> None:
    split = _two_classes(engine)
    _vanguard(engine, dict(reversed(split.items())))

    [saved] = list_instruments(engine)

    assert list(saved.multi_asset_split) == list(split)


def test_the_multi_asset_class_stays_the_one_that_is_split_after_a_rename(engine: Engine) -> None:
    multi = _class_named(engine, "Multi-asset").id
    _vanguard(engine)

    rename_asset_class(engine, multi, "Fundusze mieszane")

    assert [c.multi_asset for c in list_asset_classes(engine) if c.id == multi] == [True]
    assert [c.name for c in list_asset_classes(engine) if c.multi_asset] == ["Fundusze mieszane"]
    assert list_instruments(engine)[0].is_multi_asset


def test_a_class_named_multi_asset_by_the_user_is_not_the_multi_asset_class(engine: Engine) -> None:
    multi = _class_named(engine, "Multi-asset").id
    rename_asset_class(engine, multi, "Fundusze mieszane")

    added = add_asset_class(engine, "Multi-asset")

    assert not added.multi_asset


def test_clearing_the_portfolio_restores_the_multi_asset_class(engine: Engine) -> None:
    rename_asset_class(engine, _class_named(engine, "Multi-asset").id, "Fundusze mieszane")

    clear_portfolio(engine)

    assert [c.name for c in list_asset_classes(engine) if c.multi_asset] == ["Multi-asset"]


def test_a_renamed_class_shows_in_the_split(engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje zagraniczne").id
    _vanguard(engine, _two_classes(engine))

    rename_asset_class(engine, stocks, "Akcje świat")

    [saved] = list_instruments(engine)
    assert saved.split_class_names[stocks] == "Akcje świat"


def test_saving_the_instrument_replaces_its_split(engine: Engine) -> None:
    added = _vanguard(engine, _two_classes(engine))
    other = _class_named(engine, "Inne").id

    update_instrument(
        engine,
        added.id,
        InstrumentDraft(added.name, added.asset_class_id, "EUR", multi_asset_split={other: Decimal(100)}),
    )

    [saved] = list_instruments(engine)
    assert saved.multi_asset_split == {other: Decimal(100)}


def test_the_split_alone_can_be_set_and_cleared(engine: Engine) -> None:
    added = _vanguard(engine)

    set_multi_asset_split(engine, added.id, _two_classes(engine))
    assert list_instruments(engine)[0].multi_asset_split == _two_classes(engine)

    set_multi_asset_split(engine, added.id, {})
    assert list_instruments(engine)[0].multi_asset_split == {}


def test_setting_a_split_that_does_not_sum_to_100_is_rejected(engine: Engine) -> None:
    added = _vanguard(engine)
    stocks = _class_named(engine, "Akcje zagraniczne").id

    with pytest.raises(InstrumentError, match="100%"):
        set_multi_asset_split(engine, added.id, {stocks: Decimal(50)})


def test_a_class_in_a_split_cannot_be_deleted(engine: Engine) -> None:
    other = _class_named(engine, "Inne").id
    _vanguard(engine, {other: Decimal(100)})

    with pytest.raises(InstrumentError, match="Vanguard LifeStrategy 80"):
        delete_asset_class(engine, other)


def test_deleting_the_instrument_removes_its_split(engine: Engine) -> None:
    other = _class_named(engine, "Inne").id
    added = _vanguard(engine, {other: Decimal(100)})

    delete_instrument(engine, added.id)

    assert list_instruments(engine) == []


def test_clearing_the_portfolio_removes_the_splits(engine: Engine) -> None:
    _vanguard(engine, _two_classes(engine))

    clear_portfolio(engine)

    assert list_instruments(engine) == []
