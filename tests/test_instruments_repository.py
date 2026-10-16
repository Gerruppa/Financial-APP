"""Saving Asset Classes and Instruments in SQLite (issue #12)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import AssetClass, DistributionPolicy, InstrumentDraft, InstrumentError
from financial_app.domain.prices import ANALIZY, BANKIER, BOSSA, YAHOO, FallbackOrderError
from financial_app.domain.transactions import TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import (
    add_asset_class,
    add_instrument,
    delete_asset_class,
    delete_instrument,
    list_asset_classes,
    list_instruments,
    rename_asset_class,
    set_fallback_order,
    update_asset_class,
    update_instrument,
)
from financial_app.persistence.transactions import add_transaction

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


def test_asset_class_without_instruments_can_be_deleted(engine: Engine) -> None:
    added = add_asset_class(engine, "Nieruchomości")

    delete_asset_class(engine, added.id)

    assert "Nieruchomości" not in [c.name for c in list_asset_classes(engine)]


def test_asset_class_with_instruments_cannot_be_deleted(engine: Engine) -> None:
    polish_stocks = _class_named(engine, "Akcje polskie")
    add_instrument(engine, InstrumentDraft("PZU", polish_stocks.id, "PLN", "GPW"))

    with pytest.raises(InstrumentError, match="instrumenty"):
        delete_asset_class(engine, polish_stocks.id)
    assert "Akcje polskie" in [c.name for c in list_asset_classes(engine)]


def test_instrument_without_transactions_can_be_deleted(engine: Engine) -> None:
    added = add_instrument(engine, InstrumentDraft("PZU", _class_named(engine, "Akcje polskie").id, "PLN", "GPW"))

    delete_instrument(engine, added.id)

    assert list_instruments(engine) == []


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


def test_currency_of_an_instrument_with_transactions_cannot_change(engine: Engine) -> None:
    [first_class, *_] = list_asset_classes(engine)
    pzu = add_instrument(engine, InstrumentDraft("PZU", first_class.id, "PLN"))
    account = add_account(engine, AccountDraft("mBank", "mBank", AccountType.REGULAR, ("PLN",)))
    add_transaction(
        engine,
        buy_or_sell(account.id, date(2026, 1, 2), TransactionType.BUY, pzu.id, Decimal(1), Decimal(10)),
    )

    with pytest.raises(InstrumentError, match="waluty"):
        update_instrument(engine, pzu.id, replace(pzu, quote_currency="USD"))
    assert update_instrument(engine, pzu.id, replace(pzu, market="GPW")).market == "GPW"


def test_a_physical_metal_keeps_its_exact_weight_and_buyback_spread_after_restart(
    db_file: Path, engine: Engine
) -> None:
    metals = _class_named(engine, "Metale i surowce")
    draft = InstrumentDraft(
        "Krugerrand 1 oz", metals.id, "USD", metal_grams=Decimal("31.1034768"), buyback_spread_percent=Decimal("4.5")
    )
    add_instrument(engine, draft)
    engine.dispose()

    [saved] = list_instruments(init_db(db_file))

    assert (saved.metal_grams, saved.buyback_spread_percent) == (Decimal("31.1034768"), Decimal("4.5"))


def test_clearing_the_metal_weight_values_the_instrument_per_unit_again(engine: Engine) -> None:
    metals = _class_named(engine, "Metale i surowce").id
    added = add_instrument(engine, InstrumentDraft("Sztabka", metals, "USD", metal_grams=Decimal(100)))

    update_instrument(engine, added.id, replace(added, metal_grams=None))

    assert list_instruments(engine)[0].metal_grams is None


def test_two_listings_of_one_isin_are_two_instruments(db_file: Path, engine: Engine) -> None:
    etfs = _class_named(engine, "Akcje zagraniczne").id
    add_instrument(engine, InstrumentDraft("ISAC", etfs, "USD", "London", isin="IE00B6R52259"))
    add_instrument(engine, InstrumentDraft("IUSQ", etfs, "EUR", "XETRA", isin="IE00B6R52259"))
    engine.dispose()

    assert [i.isin for i in list_instruments(init_db(db_file))] == ["IE00B6R52259", "IE00B6R52259"]


def test_fund_details_are_kept_exactly_after_restart(db_file: Path, engine: Engine) -> None:
    etfs = _class_named(engine, "Akcje zagraniczne").id
    draft = InstrumentDraft(
        "ISAC",
        etfs,
        "USD",
        ter_percent=Decimal("0.075"),
        distribution_policy=DistributionPolicy.DISTRIBUTING,
        domicile="Irlandia",
    )
    add_instrument(engine, draft)
    engine.dispose()

    [saved] = list_instruments(init_db(db_file))

    assert (saved.ter_percent, saved.distribution_policy, saved.domicile) == (
        Decimal("0.075"),
        DistributionPolicy.DISTRIBUTING,
        "Irlandia",
    )


def test_clearing_fund_details_removes_them(engine: Engine) -> None:
    etfs = _class_named(engine, "Akcje zagraniczne").id
    added = add_instrument(
        engine,
        InstrumentDraft(
            "ISAC", etfs, "USD", ter_percent=Decimal("0.2"), distribution_policy=DistributionPolicy.ACCUMULATING
        ),
    )

    update_instrument(engine, added.id, replace(added, ter_percent=None, distribution_policy=None))

    [saved] = list_instruments(engine)
    assert (saved.ter_percent, saved.distribution_policy) == (None, None)


def test_seeded_asset_classes_have_the_spec_fallback_orders(engine: Engine) -> None:
    assert _class_named(engine, "Akcje polskie").fallback_order == (BOSSA, YAHOO)
    assert _class_named(engine, "Multi-asset").fallback_order == (ANALIZY, BANKIER, YAHOO, BOSSA)
    assert _class_named(engine, "Gotówka").fallback_order == ()


def test_a_changed_fallback_order_is_kept_and_reaches_the_instruments_after_restart(
    db_file: Path, engine: Engine
) -> None:
    stocks = _class_named(engine, "Akcje polskie")
    add_instrument(engine, InstrumentDraft("PZU", stocks.id, "PLN", "GPW"))

    set_fallback_order(engine, stocks.id, [YAHOO])

    restarted = init_db(db_file)
    assert _class_named(restarted, "Akcje polskie").fallback_order == (YAHOO,)
    assert list_instruments(restarted)[0].fallback_order == (YAHOO,)


def test_a_fallback_order_naming_a_source_twice_is_rejected(engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje polskie")

    with pytest.raises(FallbackOrderError):
        set_fallback_order(engine, stocks.id, [YAHOO, YAHOO])
    assert _class_named(engine, "Akcje polskie").fallback_order == (BOSSA, YAHOO)


def test_a_new_asset_class_gets_the_order_of_inne(engine: Engine) -> None:
    set_fallback_order(engine, _class_named(engine, "Inne").id, [BANKIER, YAHOO])

    assert add_asset_class(engine, "Nieruchomości").fallback_order == (BANKIER, YAHOO)


def test_a_new_asset_class_gets_the_default_order_of_inne_when_inne_was_renamed(engine: Engine) -> None:
    rename_asset_class(engine, _class_named(engine, "Inne").id, "Pozostałe")

    assert add_asset_class(engine, "Nieruchomości").fallback_order == (ANALIZY, BANKIER, YAHOO, BOSSA)


def test_a_new_asset_class_may_be_given_its_own_order(engine: Engine) -> None:
    assert add_asset_class(engine, "Nieruchomości", [YAHOO]).fallback_order == (YAHOO,)


def test_renaming_an_asset_class_keeps_its_fallback_order(engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje polskie")

    assert rename_asset_class(engine, stocks.id, "Akcje GPW").fallback_order == (BOSSA, YAHOO)


def test_a_class_with_a_taken_name_keeps_both_its_name_and_its_order(engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje polskie")

    with pytest.raises(InstrumentError, match="już istnieje"):
        update_asset_class(engine, stocks.id, "Inne", [YAHOO])
    assert _class_named(engine, "Akcje polskie").fallback_order == (BOSSA, YAHOO)


def test_a_class_is_renamed_and_given_a_new_order_at_once(engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje polskie")

    update_asset_class(engine, stocks.id, "Akcje GPW", [YAHOO])

    assert _class_named(engine, "Akcje GPW").fallback_order == (YAHOO,)


def test_quantity_decimals_are_saved_and_changed(engine: Engine) -> None:
    crypto = _class_named(engine, "Kryptowaluty").id
    added = add_instrument(engine, InstrumentDraft("Bitcoin", crypto, "USD", quantity_decimals=8))
    assert added.quantity_decimals == 8

    update_instrument(engine, added.id, replace(added, quantity_decimals=4))

    [saved] = list_instruments(engine)
    assert saved.quantity_decimals == 4
