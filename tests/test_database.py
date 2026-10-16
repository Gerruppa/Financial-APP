from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from financial_app.persistence.db import MIGRATIONS_DIR, init_db, open_engine
from financial_app.persistence.instruments import list_asset_classes, list_instruments
from financial_app.persistence.models import Base


def test_init_db_creates_database_file_and_schema_from_scratch(tmp_path: Path) -> None:
    db_file = tmp_path / "nested" / "app.sqlite3"

    engine = init_db(db_file)

    assert db_file.exists()
    assert "app_settings" in inspect(engine).get_table_names()


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    db_file = tmp_path / "app.sqlite3"
    init_db(db_file).dispose()

    engine = init_db(db_file)

    assert "app_settings" in inspect(engine).get_table_names()


def test_migrations_match_the_orm_models(tmp_path: Path) -> None:
    engine = init_db(tmp_path / "app.sqlite3")

    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    assert diff == []


def test_upgrading_gives_each_existing_asset_class_its_default_fallback_order(tmp_path: Path) -> None:
    db_file = tmp_path / "app.sqlite3"
    engine = open_engine(db_file)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0017")
        connection.execute(text("INSERT INTO asset_classes (name, position) VALUES ('Nieruchomości', 12)"))

    orders = {c.name: c.fallback_order for c in list_asset_classes(init_db(db_file))}

    assert orders["Akcje polskie"] == ("bossa", "yahoo")
    assert orders["Waluty"] == ()
    assert orders["Nieruchomości"] == ("analizy", "bankier", "yahoo", "bossa")


def test_upgrading_clears_the_imported_manual_prices_of_bond_series_only(tmp_path: Path) -> None:
    db_file = tmp_path / "app.sqlite3"
    engine = open_engine(db_file)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0022")
        for name, class_name in (
            ("EDO0836", "Obligacje skarbowe polskie"),
            ("PKN0726", "Obligacje skarbowe polskie"),  # no retail Series
            ("TOS0729", "Obligacje korporacyjne polskie"),
        ):
            connection.execute(
                text(
                    "INSERT INTO instruments (name, asset_class_id, quote_currency, market, manual_price)"
                    " SELECT :name, id, 'PLN', '', '103.5' FROM asset_classes WHERE name = :class_name"
                ),
                {"name": name, "class_name": class_name},
            )

    prices = {i.name: i.manual_price for i in list_instruments(init_db(db_file))}

    assert prices == {"EDO0836": None, "PKN0726": Decimal("103.5"), "TOS0729": Decimal("103.5")}


def test_upgrading_quotes_polish_treasury_bonds_through_bossa_and_drops_bossas_percent_quotes(tmp_path: Path) -> None:
    db_file = tmp_path / "app.sqlite3"
    engine = open_engine(db_file)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0024")
        for name, class_name, source in (
            ("DS1030", "Obligacje skarbowe polskie", "bossa"),
            ("ACH0427", "Obligacje korporacyjne polskie", "bossa"),
            ("PZU", "Akcje polskie", "bossa"),
            ("XYZ0130", "Obligacje korporacyjne polskie", "yahoo"),
        ):
            connection.execute(
                text(
                    "INSERT INTO instruments (name, asset_class_id, quote_currency, market)"
                    " SELECT :name, id, 'PLN', '' FROM asset_classes WHERE name = :class_name"
                ),
                {"name": name, "class_name": class_name},
            )
            connection.execute(
                text(
                    "INSERT INTO quotes (instrument_id, day, price, currency, source, fetched_at)"
                    " SELECT id, '2026-10-02', '101.00', 'PLN', :source, '2026-10-02 18:00:00'"
                    " FROM instruments WHERE name = :name"
                ),
                {"name": name, "source": source},
            )

    engine = init_db(db_file)

    orders = {c.name: c.fallback_order for c in list_asset_classes(engine)}
    assert orders["Obligacje skarbowe polskie"] == ("bossa",)
    with engine.connect() as connection:
        quoted = connection.execute(
            text("SELECT name FROM quotes JOIN instruments ON instruments.id = quotes.instrument_id ORDER BY name")
        ).scalars()
        assert list(quoted) == ["PZU", "XYZ0130"]


def test_upgrading_keeps_a_treasury_bond_order_the_user_chose(tmp_path: Path) -> None:
    db_file = tmp_path / "app.sqlite3"
    engine = open_engine(db_file)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0024")
        connection.execute(
            text("UPDATE asset_classes SET fallback_order = 'yahoo' WHERE name = 'Obligacje skarbowe polskie'")
        )

    orders = {c.name: c.fallback_order for c in list_asset_classes(init_db(db_file))}

    assert orders["Obligacje skarbowe polskie"] == ("yahoo",)
