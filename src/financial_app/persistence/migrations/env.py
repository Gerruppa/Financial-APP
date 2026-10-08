"""Alembic environment.

The app passes its own connection (see ``db.init_db``). The ``alembic`` CLI
connects to the user's REAL database (``paths.database_path()``), so prefer
``revision --autogenerate`` there and point FINANCIAL_APP_DATA_DIR at a scratch
folder before running ``upgrade``/``downgrade`` by hand.
"""

from alembic import context
from sqlalchemy import Connection

from financial_app.persistence.db import open_engine
from financial_app.persistence.models import Base
from financial_app.persistence.paths import database_path


def run_migrations(connection: Connection) -> None:
    # batch mode lets ALTER-style changes work on SQLite
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run_migrations(connection)
else:
    with open_engine(database_path()).begin() as cli_connection:
        run_migrations(cli_connection)
