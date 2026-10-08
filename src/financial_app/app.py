"""Application entry point: back up and prepare the database, then open the NiceGUI window."""

import sys
from pathlib import Path

from nicegui import ui

from financial_app.persistence.backup import backup_database
from financial_app.persistence.db import init_db
from financial_app.persistence.paths import backups_dir, database_path, log_path
from financial_app.ui.shell import APP_TITLE, build_shell


def attach_log_when_windowless(path: Path) -> None:
    """Send output to ``path`` when started without a console (pythonw), where uvicorn would crash on None."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Kept open for the life of the process; overwritten at each start so it never grows unbounded.
    log = open(path, "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log


def main() -> None:
    attach_log_when_windowless(log_path())
    # Back up before migrating, so a failed migration never touches the only copy.
    backup_database(database_path(), backups_dir())
    init_db(database_path()).dispose()
    ui.run(build_shell, title=APP_TITLE, native=True, window_size=(1400, 900), reload=False, language="pl")
