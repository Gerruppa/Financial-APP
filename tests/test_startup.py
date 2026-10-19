"""Smoke test of the real entry point: one command builds the database and shows the window."""

from pathlib import Path

import pytest
from nicegui.testing import user_simulation

from financial_app import app
from financial_app.persistence.db import init_db
from financial_app.persistence.paths import backups_dir, database_path

MAIN_FILE = Path(__file__).resolve().parents[1] / "main.py"


async def test_app_starts_with_database_in_data_dir_and_shows_dashboard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))

    async with user_simulation(main_file=MAIN_FILE) as user:
        await user.open("/")

        await user.should_see("Dashboard")
    assert (tmp_path / "financial_app.sqlite3").exists()


async def test_each_start_backs_up_the_existing_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))
    init_db(database_path()).dispose()

    async with user_simulation(main_file=MAIN_FILE) as user:
        await user.open("/")

    assert len(list(backups_dir().iterdir())) == 1


def test_failed_move_stops_the_start_with_a_polish_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def locked() -> None:
        raise PermissionError("in use")

    shown: list[str] = []
    monkeypatch.setattr(app, "adopt_legacy_data_dir", locked)
    monkeypatch.setattr(app, "show_startup_error", shown.append)

    with pytest.raises(SystemExit):
        app.main()

    assert len(shown) == 1 and "Zamknij" in shown[0]
