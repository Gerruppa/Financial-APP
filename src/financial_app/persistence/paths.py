"""Location of the user's data, always outside the repository (ADR-0001)."""

import os
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "KAPITA"
# The folder's name before the app was called KAPITA (1.0); its data moves over at start
LEGACY_APP_NAME = "FinancialApp"
# The variable and the file names keep their pre-1.0 names, so existing setups and data still work
DATA_DIR_ENV = "FINANCIAL_APP_DATA_DIR"
DATABASE_FILE = "financial_app.sqlite3"
BACKUPS_DIR = "backups"
LOG_FILE = "financial_app.log"
# The list of Users, the one file the Users share (ADR-0010); each User's folder is named by a fixed id
USERS_FILE = "users.json"
# Before anyone has signed in there is no User's folder to log to
STARTUP_LOG_FILE = "startup.log"


def data_dir() -> Path:
    """The app-data folder (e.g. %LOCALAPPDATA%/KAPITA); override with FINANCIAL_APP_DATA_DIR."""
    override = os.environ.get(DATA_DIR_ENV)
    return Path(override) if override else Path(user_data_dir(APP_NAME, appauthor=False))


def startup_log_path() -> Path:
    return data_dir() / STARTUP_LOG_FILE


def database_path(folder: Path | None = None) -> Path:
    """The database in ``folder`` (a User's), or in the app-data folder itself, where it lay before Users."""
    return (folder or data_dir()) / DATABASE_FILE


def backups_dir(folder: Path | None = None) -> Path:
    return (folder or data_dir()) / BACKUPS_DIR


def log_path(folder: Path | None = None) -> Path:
    return (folder or data_dir()) / LOG_FILE


def adopt_legacy_data_dir() -> None:
    """Move the pre-1.0 FinancialApp folder to the KAPITA one, unless FINANCIAL_APP_DATA_DIR points elsewhere."""
    if not os.environ.get(DATA_DIR_ENV):
        move_legacy_data_dir(Path(user_data_dir(LEGACY_APP_NAME, appauthor=False)), data_dir())


def move_legacy_data_dir(legacy: Path, current: Path) -> None:
    """Rename ``legacy`` to ``current``; a ``current`` that already exists is never touched."""
    if legacy.is_dir() and not current.exists():
        legacy.rename(current)
