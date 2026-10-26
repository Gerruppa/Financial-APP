"""Application entry point: the login screen, then the User's database backed up and prepared and the NiceGUI shell
on it (spec 2.1, ADR-0010)."""

import argparse
import ctypes
import os
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from functools import partial
from pathlib import Path
from typing import Any, TextIO

from nicegui import ui
from sqlalchemy import Engine

from financial_app.persistence.backup import backup_database
from financial_app.persistence.db import init_db
from financial_app.persistence.paths import (
    DATA_DIR_ENV,
    adopt_legacy_data_dir,
    backups_dir,
    data_dir,
    database_path,
    log_path,
    startup_log_path,
)
from financial_app.persistence.users import User, UserError, UserStore
from financial_app.sources.app_update import UpdateSource
from financial_app.sources.demo_data import seed_demo_data
from financial_app.ui.login import build_login
from financial_app.ui.shell import APP_ICON, APP_TITLE, build_shell, stop_background_work
from financial_app.ui.user_section import UserSection

MB_ICONERROR = 0x10
DEMO_USER = "Demo"
LEGACY_MOVE_FAILED = (
    r"KAPITA nie może przenieść danych z folderu %LOCALAPPDATA%\FinancialApp do %LOCALAPPDATA%\KAPITA, "
    "bo są w użyciu. Zamknij poprzednią wersję aplikacji i uruchom KAPITA ponownie."
)


def _no_console(stream: TextIO | None) -> bool:
    """No console behind ``stream``: None, or the os.devnull pywebview puts in its place when imported."""
    return stream is None or getattr(stream, "name", None) == os.devnull


# The log file this module opened, kept open for the life of the process
_log: TextIO | None = None


def attach_log_when_windowless(path: Path) -> None:
    """Send output to ``path`` without a console (pythonw, KAPITA.exe), where uvicorn would crash on None.

    Called again at a sign-in, it moves the output from the startup log to that User's log."""
    global _log
    ours = _log
    out = _no_console(sys.stdout) or (ours is not None and sys.stdout is ours)
    err = _no_console(sys.stderr) or (ours is not None and sys.stderr is ours)
    if not (out or err):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Overwritten at each start so it never grows unbounded.
    log = open(path, "w", encoding="utf-8", buffering=1)
    if out:
        sys.stdout = log
    if err:
        sys.stderr = log
    _log = log
    if ours is not None:
        ours.close()


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


def demo_dir() -> Path:
    """The demo's data folder in TEMP, apart from the user's real one."""
    return Path(tempfile.gettempdir()) / "KAPITA-demo"


def start_demo_database() -> None:
    """Point the app at a demo folder in TEMP and fill a fresh database there; real data stays untouched."""
    os.environ[DATA_DIR_ENV] = str(demo_dir())
    database_path().unlink(missing_ok=True)
    engine = init_db(database_path())
    seed_demo_data(engine, date.today())
    engine.dispose()


@dataclass
class SignedIn:
    """The User at the window: whose folder it is and the open database in it."""

    pseudonym: str
    folder: Path
    engine: Engine
    # None for the demo's made-up User, who is not in the list of Users
    user: User | None = None


class Session:
    """Who is signed in; at most one User at a time, as the app serves one computer."""

    def __init__(self) -> None:
        self.current: SignedIn | None = None

    def open(self, pseudonym: str, folder: Path, user: User | None = None) -> None:
        """Open the database in ``folder`` for ``pseudonym``, backed up first and then migrated."""
        attach_log_when_windowless(log_path(folder))
        # Back up before migrating, so a failed migration never touches the only copy.
        backup_database(database_path(folder), backups_dir(folder))
        self.current = SignedIn(pseudonym, folder, init_db(database_path(folder)), user)

    def close(self) -> None:
        """Sign out: the User's background work stops and their database closes."""
        if self.current is not None:
            engine = self.current.engine
            stop_background_work(engine)
            engine.dispose()
            self.current = None


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
    attach_log_when_windowless(startup_log_path())
    store = UserStore(data_dir())
    session = Session()
    if args.demo:
        # The demo skips the login screen with a made-up User without a password
        session.open(DEMO_USER, data_dir())
    # The demo skips the refresh at start: its Instruments have Manual Prices only and screenshots stay offline
    refresh_at_start = not args.demo

    def signed_in(user: User) -> None:
        session.open(user.pseudonym, store.folder(user), user)
        ui.navigate.reload()

    def switch_user() -> None:
        session.close()
        # The address of the User who left is of no use to the next one
        ui.run_javascript("window.location.assign('/')")

    def changed(user: User) -> None:
        assert session.current is not None
        renamed = user.pseudonym != session.current.pseudonym
        session.current.user = user
        session.current.pseudonym = user.pseudonym
        if renamed:
            # The avatar and its menu carry the pseudonym
            ui.navigate.reload()

    def deleted(user: User, password: str) -> None:
        # The database and the log are closed first: Windows refuses to delete a folder with an open file in it
        session.close()
        attach_log_when_windowless(startup_log_path())
        try:
            store.delete(user, password)
        except UserError as refusal:
            ui.notify(str(refusal), type="negative")
        ui.run_javascript("window.location.assign('/')")

    def root() -> None:
        if session.current is None:
            build_login(store, signed_in)
        else:
            signed = session.current.user
            build_shell(
                session.current.engine,
                refresh_at_start=refresh_at_start,
                on_switch_user=None if args.demo else switch_user,
                pseudonym=session.current.pseudonym,
                updates=None if args.demo else UpdateSource.real(),
                user_section=None if signed is None else UserSection(store, signed, changed, partial(deleted, signed)),
            )

    # window_size alone switches NiceGUI to native mode, so the browser mode leaves it out; the native window finds a
    # free port itself, the browser mode opens no tab (the URL is in the console)
    window: dict[str, Any] = (
        {"port": args.port, "show": False} if browser else {"native": True, "window_size": (1400, 900)}
    )
    ui.run(
        root,
        title=APP_TITLE,
        # In native mode on Windows the .ico is also the window's icon
        favicon=APP_ICON,
        reload=False,
        language="pl",
        **window,
    )
