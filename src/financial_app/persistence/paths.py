"""Location of the user's data, always outside the repository (ADR-0001)."""

import os
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "FinancialApp"
DATA_DIR_ENV = "FINANCIAL_APP_DATA_DIR"
DATABASE_FILE = "financial_app.sqlite3"
BACKUPS_DIR = "backups"
LOG_FILE = "financial_app.log"


def data_dir() -> Path:
    """The app-data folder (e.g. %LOCALAPPDATA%/FinancialApp); override with FINANCIAL_APP_DATA_DIR."""
    override = os.environ.get(DATA_DIR_ENV)
    return Path(override) if override else Path(user_data_dir(APP_NAME, appauthor=False))


def database_path() -> Path:
    return data_dir() / DATABASE_FILE


def backups_dir() -> Path:
    return data_dir() / BACKUPS_DIR


def log_path() -> Path:
    return data_dir() / LOG_FILE
