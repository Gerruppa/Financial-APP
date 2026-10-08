from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from financial_app.persistence.db import init_db
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
