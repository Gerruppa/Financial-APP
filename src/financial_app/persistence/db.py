"""Opening the SQLite database and bringing its schema up to date."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def open_engine(path: Path) -> Engine:
    """Engine for the SQLite file at ``path``, creating its folder if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # No pool: a connection closes when its work ends, so a worker thread that was still running as the User signed
    # out cannot leave the file open (Windows would refuse to delete the User's folder)
    return create_engine(f"sqlite:///{path}", poolclass=NullPool)


def init_db(path: Path) -> Engine:
    """Create the database file if needed and apply all pending migrations."""
    engine = open_engine(path)
    migrate(engine)
    return engine


def migrate(engine: Engine) -> None:
    """Apply all pending migrations to the database of ``engine`` (also an in-memory one, for tests)."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
