from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from financial_app.domain.benchmarks import Benchmark, BenchmarkKind
from financial_app.domain.prices import STOOQ
from financial_app.persistence.benchmarks import ensure_default_benchmarks, list_benchmarks
from financial_app.persistence.db import MIGRATIONS_DIR, init_db, open_engine
from financial_app.persistence.instruments import list_asset_classes, list_instruments
from financial_app.persistence.models import Base
from financial_app.persistence.settings import BENCHMARKS_SEEDED, load_setting


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


def test_upgrading_drops_the_first_gpw_benchmarks_left_on_stooq_so_the_etfs_come_in(tmp_path: Path) -> None:
    # As the first defaults left them: WSE:WIG and WSE:SWIG80TR with only their Stooq symbol (issue #91)
    db_file = tmp_path / "app.sqlite3"
    engine = open_engine(db_file)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0027")
        # In SQL, as the models already have the columns of later revisions
        other = connection.execute(text("SELECT id FROM asset_classes WHERE name = 'Inne'")).scalar_one()
        for position, (name, symbol) in enumerate((("WSE:WIG", "wig"), ("WSE:SWIG80TR", "swig80tr"))):
            instrument = connection.execute(
                text(
                    "INSERT INTO instruments (name, asset_class_id, quote_currency, market, isin, domicile)"
                    " VALUES (:name, :class_id, 'PLN', '', '', '') RETURNING id"
                ),
                {"name": name, "class_id": other},
            ).scalar_one()
            connection.execute(
                text("INSERT INTO source_symbols (instrument_id, source, symbol) VALUES (:id, :source, :symbol)"),
                {"id": instrument, "source": STOOQ, "symbol": symbol},
            )
            connection.execute(
                text(
                    "INSERT INTO benchmarks (kind, instrument_id, offset, shown, position)"
                    " VALUES ('instrument', :id, '0', 1, :position)"
                ),
                {"id": instrument, "position": position},
            )
        connection.execute(text("INSERT INTO benchmarks (kind, offset, shown, position) VALUES ('cpi', '0', 1, 2)"))
        connection.execute(text("INSERT INTO app_settings (key, value) VALUES (:key, '1')"), {"key": BENCHMARKS_SEEDED})
    engine.dispose()

    upgraded = init_db(db_file)

    assert list_benchmarks(upgraded) == [Benchmark(BenchmarkKind.CPI)]
    assert list_instruments(upgraded) == []
    assert load_setting(upgraded, BENCHMARKS_SEEDED) is None
    assert ensure_default_benchmarks(upgraded)
    names = {i.name for i in list_instruments(upgraded)}
    assert {"WSE:ETFBW20TR", "WSE:ETFBM40TR", "WSE:ETFBS80TR"} <= names
    assert len(list_benchmarks(upgraded)) == 7


def test_upgrading_gives_each_instrument_the_decimals_its_quantities_use_and_crypto_eight(tmp_path: Path) -> None:
    db_file = tmp_path / "app.sqlite3"
    engine = open_engine(db_file)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0029")
        classes: dict[str, int] = dict(connection.execute(text("SELECT name, id FROM asset_classes")).all())
        connection.execute(
            text(
                "INSERT INTO accounts (id, name, broker, account_type, exclude_fx_result, active)"
                " VALUES (1, 'XTB', '', 'regular', 0, 1)"
            )
        )
        for instrument_id, name, class_name in (
            (1, "CD Projekt", "Akcje polskie"),
            (2, "Fundusz", "Inne"),
            (3, "Bitcoin", "Kryptowaluty"),
            (4, "Bez transakcji", "Inne"),
        ):
            connection.execute(
                text(
                    "INSERT INTO instruments (id, name, asset_class_id, quote_currency, market, isin, domicile)"
                    " VALUES (:id, :name, :class_id, 'PLN', '', '', '')"
                ),
                {"id": instrument_id, "name": name, "class_id": classes[class_name]},
            )
        for instrument_id, quantity in ((1, "10"), (1, "2.50"), (2, "1.125"), (2, "3.5"), (3, "0.1")):
            connection.execute(
                text(
                    "INSERT INTO transactions (account_id, date, transaction_type, actual_amount, comment,"
                    " instrument_id, quantity) VALUES (1, '2026-01-02', 'buy', '100', '', :instrument, :quantity)"
                ),
                {"instrument": instrument_id, "quantity": quantity},
            )
    engine.dispose()

    upgraded = init_db(db_file)

    decimals = {i.name: i.quantity_decimals for i in list_instruments(upgraded)}
    # Trailing zeros are no decimals the user needed: 2.50 is 2.5
    assert decimals == {"CD Projekt": 1, "Fundusz": 3, "Bitcoin": 8, "Bez transakcji": 0}


def test_upgrading_gives_each_instrument_a_type_from_what_is_saved(tmp_path: Path) -> None:
    db_file = tmp_path / "app.sqlite3"
    engine = open_engine(db_file)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0036")
        classes: dict[str, int] = dict(connection.execute(text("SELECT name, id FROM asset_classes")).all())
        for instrument_id, name, class_name, grams in (
            (1, "EDO0136", "Obligacje skarbowe polskie", None),
            (2, "Krugerrand", "Metale i surowce", "31.1034768"),
            (3, "Bitcoin", "Kryptowaluty", None),
            (4, "PZU Akcji", "Akcje polskie", None),
            (5, "Beta ETF WIG20TR", "Akcje polskie", None),
            (6, "WisdomTree Physical Gold ETC", "Metale i surowce", None),
            (7, "CD Projekt", "Akcje polskie", None),
            (8, "Etfowy fundusz", "Inne", None),
        ):
            connection.execute(
                text(
                    "INSERT INTO instruments (id, name, asset_class_id, quote_currency, market, isin, domicile,"
                    " metal_grams) VALUES (:id, :name, :class_id, 'PLN', '', '', '', :grams)"
                ),
                {"id": instrument_id, "name": name, "class_id": classes[class_name], "grams": grams},
            )
        connection.execute(
            text("INSERT INTO source_symbols (instrument_id, source, symbol) VALUES (4, 'analizy', 'PZU60')")
        )
    engine.dispose()

    upgraded = init_db(db_file)

    types = {i.name: i.instrument_type.label for i in list_instruments(upgraded)}
    assert types == {
        "EDO0136": "Obligacja skarbowa",
        "Krugerrand": "Metal fizyczny",
        "Bitcoin": "Kryptowaluta",
        "PZU Akcji": "Fundusz",
        "Beta ETF WIG20TR": "ETF",
        "WisdomTree Physical Gold ETC": "ETC",
        "CD Projekt": "Inne",
        # "ETF" counts only as a word of the name
        "Etfowy fundusz": "Inne",
    }
