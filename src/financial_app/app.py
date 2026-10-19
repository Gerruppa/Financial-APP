"""Application entry point: back up and prepare the database, then open the NiceGUI window."""

import ctypes
import os
import sys
from pathlib import Path
from typing import TextIO

from nicegui import ui

from financial_app.persistence.backup import backup_database
from financial_app.persistence.db import init_db
from financial_app.persistence.paths import adopt_legacy_data_dir, backups_dir, database_path, log_path
from financial_app.ui.shell import APP_ICON, APP_TITLE, build_shell

MB_ICONERROR = 0x10
LEGACY_MOVE_FAILED = (
    r"KAPITA nie może przenieść danych z folderu %LOCALAPPDATA%\FinancialApp do %LOCALAPPDATA%\KAPITA, "
    "bo są w użyciu. Zamknij poprzednią wersję aplikacji i uruchom KAPITA ponownie."
)


def _no_console(stream: TextIO | None) -> bool:
    """No console behind ``stream``: None, or the os.devnull pywebview puts in its place when imported."""
    return stream is None or getattr(stream, "name", None) == os.devnull


def attach_log_when_windowless(path: Path) -> None:
    """Send output to ``path`` without a console (pythonw, KAPITA.exe), where uvicorn would crash on None."""
    if not _no_console(sys.stdout) and not _no_console(sys.stderr):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Kept open for the life of the process; overwritten at each start so it never grows unbounded.
    log = open(path, "w", encoding="utf-8", buffering=1)
    if _no_console(sys.stdout):
        sys.stdout = log
    if _no_console(sys.stderr):
        sys.stderr = log


def show_startup_error(message: str) -> None:
    """A Windows message box, since a start without a console has nowhere else to say why it stopped."""
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, APP_TITLE, MB_ICONERROR)
    else:
        print(message, file=sys.stderr)


def main() -> None:
    # Before the log opens, which would create the new folder and block the move
    try:
        adopt_legacy_data_dir()
    except OSError:
        # Nothing was moved and the KAPITA folder was not created, so the next start tries again
        show_startup_error(LEGACY_MOVE_FAILED)
        raise SystemExit(1) from None
    attach_log_when_windowless(log_path())
    # Back up before migrating, so a failed migration never touches the only copy.
    backup_database(database_path(), backups_dir())
    engine = init_db(database_path())
    ui.run(
        lambda: build_shell(engine, refresh_at_start=True),
        title=APP_TITLE,
        # In native mode on Windows the .ico is also the window's icon
        favicon=APP_ICON,
        native=True,
        window_size=(1400, 900),
        reload=False,
        language="pl",
    )
