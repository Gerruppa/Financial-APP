"""Opening the SQLite database and bringing its schema up to date."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def open_engine(path: Path) -> Engine:
    """Engine for the SQLite file at ``path``, creating its folder if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}")


def init_db(path: Path) -> Engine:
    """Create the database file if needed and apply all pending migrations."""
    engine = open_engine(path)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    return engine
