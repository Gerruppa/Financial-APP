"""Application entry point: back up and prepare the database, then open the NiceGUI window."""

import argparse
import ctypes
import os
import sys
import tempfile
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any, TextIO

from nicegui import ui

from financial_app.persistence.backup import backup_database
from financial_app.persistence.db import init_db
from financial_app.persistence.paths import (
    DATA_DIR_ENV,
    adopt_legacy_data_dir,
    backups_dir,
    database_path,
    log_path,
)
from financial_app.sources.demo_data import seed_demo_data
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


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """``--browser`` serves the UI on localhost instead of the native window; ``--demo`` adds a made-up Portfolio."""
    # No abbreviations: under the startup tests sys.argv holds pytest's own options
    parser = argparse.ArgumentParser(prog="KAPITA", allow_abbrev=False)
    parser.add_argument("--browser", action="store_true", help="UI w przeglądarce (localhost) zamiast okna")
    parser.add_argument("--demo", action="store_true", help="przeglądarka i świeża, zmyślona baza w folderze TEMP")
    parser.add_argument("--port", type=int, default=8080)
    # parse_known_args: the frozen KAPITA.exe may get arguments of its own (multiprocessing)
    return parser.parse_known_args(argv)[0]


def start_demo_database() -> None:
    """Point the app at a demo folder in TEMP and fill a fresh database there; real data stays untouched."""
    folder = Path(tempfile.gettempdir()) / "KAPITA-demo"
    os.environ[DATA_DIR_ENV] = str(folder)
    database_path().unlink(missing_ok=True)
    engine = init_db(database_path())
    seed_demo_data(engine, date.today())
    engine.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    browser = args.browser or args.demo
    if args.demo:
        start_demo_database()
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
    # The demo skips the refresh at start: its Instruments have Manual Prices only and screenshots stay offline
    refresh_at_start = not args.demo
    # window_size alone switches NiceGUI to native mode, so the browser mode leaves it out; the native window finds a
    # free port itself, the browser mode opens no tab (the URL is in the console)
    window: dict[str, Any] = (
        {"port": args.port, "show": False} if browser else {"native": True, "window_size": (1400, 900)}
    )
    ui.run(
        lambda: build_shell(engine, refresh_at_start=refresh_at_start),
        title=APP_TITLE,
        # In native mode on Windows the .ico is also the window's icon
        favicon=APP_ICON,
        reload=False,
        language="pl",
        **window,
    )
