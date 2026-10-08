"""Application entry point: prepare the database, then open the NiceGUI window."""

from nicegui import ui

from financial_app.persistence.db import init_db
from financial_app.persistence.paths import database_path
from financial_app.ui.shell import APP_TITLE, build_shell


def main() -> None:
    init_db(database_path()).dispose()
    ui.run(build_shell, title=APP_TITLE, native=True, window_size=(1400, 900), reload=False, language="pl")
